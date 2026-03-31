import json
from datetime import datetime, timezone, timedelta

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_infra import llm_text
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


def _write_outputs(agent_name: str, call_number: int, summary: str, payload: dict):
    write_text_file(f"{agent_name}_{call_number}.txt", summary)
    write_text_file(f"{agent_name}_{call_number}.json", json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _aws_json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _require_aws_authorization(state: dict):
    if not state.get("aws_authorized", False):
        raise PermissionError(
            "AWS agents require explicit authorization. Set state['aws_authorized']=True only for AWS accounts and actions you are permitted to access."
        )


def _get_boto3_session(state: dict):
    try:
        import boto3
    except Exception as exc:
        raise ImportError("boto3 is required for AWS agents.") from exc

    session_kwargs = {}
    if state.get("aws_profile"):
        session_kwargs["profile_name"] = state["aws_profile"]
    if state.get("aws_region"):
        session_kwargs["region_name"] = state["aws_region"]
    return boto3.Session(**session_kwargs)


def _client(session, service_name: str, state: dict):
    region = state.get("aws_region")
    if region:
        return session.client(service_name, region_name=region)
    return session.client(service_name)


def _resource(session, service_name: str, state: dict):
    region = state.get("aws_region")
    if region:
        return session.resource(service_name, region_name=region)
    return session.resource(service_name)


def _is_mutating(service: str, operation: str) -> bool:
    return (service, operation) in {
        ("ec2", "start_instances"),
        ("ec2", "stop_instances"),
        ("s3", "put_object"),
        ("lambda", "invoke"),
        ("ssm", "send_command"),
    }


def _execute_allowed_operation(session, service: str, operation: str, parameters: dict, state: dict):
    if _is_mutating(service, operation) and not state.get("aws_allow_mutation", False):
        raise PermissionError(
            f"AWS operation {service}.{operation} is mutating. Set state['aws_allow_mutation']=True to allow it."
        )

    client = _client(session, service, state)
    allowed = {
        "sts": {"get_caller_identity"},
        "ec2": {"describe_instances", "start_instances", "stop_instances"},
        "s3": {"list_buckets", "list_objects_v2", "put_object"},
        "lambda": {"list_functions", "invoke"},
        "logs": {"filter_log_events"},
        "cloudwatch": {"describe_alarms"},
        "ssm": {"send_command"},
    }
    if operation not in allowed.get(service, set()):
        raise ValueError(f"AWS operation {service}.{operation} is not in the allowed automation list.")

    method = getattr(client, operation, None)
    if method is None:
        raise AttributeError(f"AWS client for {service} does not support operation {operation}.")
    response = method(**(parameters or {}))
    try:
        return response
    except Exception:
        return {"response": str(response)}


def aws_scope_guard_agent(state):
    _, task_content, _ = begin_agent_session(state, "aws_scope_guard_agent")
    state["aws_scope_guard_calls"] = state.get("aws_scope_guard_calls", 0) + 1
    call_number = state["aws_scope_guard_calls"]

    authorized = bool(state.get("aws_authorized", False))
    requested_services = state.get("aws_services") or []
    request_text = task_content or state.get("current_objective") or state.get("user_query", "")
    identity = {}
    creds_available = False
    error_text = ""

    try:
        session = _get_boto3_session(state)
        credentials = session.get_credentials()
        creds_available = credentials is not None
        if creds_available:
            identity = _client(session, "sts", state).get_caller_identity()
    except Exception as exc:
        error_text = str(exc)

    payload = {
        "authorized": authorized,
        "credentials_available": creds_available,
        "identity": identity,
        "requested_services": requested_services,
        "request": request_text,
        "error": error_text,
        "decision": "allow" if authorized and creds_available else "deny",
        "disallowed_actions": [
            "unauthorized AWS access",
            "mutating operations without explicit aws_allow_mutation=True",
        ],
    }
    summary = (
        f"Authorized: {authorized}\n"
        f"Credentials available: {creds_available}\n"
        f"Requested services: {', '.join(requested_services) if requested_services else 'not specified'}\n"
        f"Account identity: {json.dumps(identity, ensure_ascii=False) if identity else 'unavailable'}\n"
        f"Decision: {payload['decision']}"
    )
    _write_outputs("aws_scope_guard_agent", call_number, summary, payload)
    state["aws_scope_report"] = payload
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "aws_scope_guard_agent",
        summary,
        f"aws_scope_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )


def aws_inventory_agent(state):
    _, task_content, _ = begin_agent_session(state, "aws_inventory_agent")
    _require_aws_authorization(state)
    state["aws_inventory_calls"] = state.get("aws_inventory_calls", 0) + 1
    call_number = state["aws_inventory_calls"]

    session = _get_boto3_session(state)
    services = state.get("aws_services") or ["ec2", "s3", "lambda", "rds"]
    inventory = {"services": {}, "region": state.get("aws_region") or session.region_name}

    log_task_update("AWS Inventory", f"AWS inventory pass #{call_number} started.", ", ".join(services))
    for service in services:
        try:
            if service == "ec2":
                response = _client(session, "ec2", state).describe_instances()
                instances = []
                for reservation in response.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        instances.append(
                            {
                                "instance_id": instance.get("InstanceId"),
                                "state": instance.get("State", {}).get("Name"),
                                "type": instance.get("InstanceType"),
                                "private_ip": instance.get("PrivateIpAddress"),
                            }
                        )
                inventory["services"]["ec2"] = instances
            elif service == "s3":
                response = _client(session, "s3", state).list_buckets()
                inventory["services"]["s3"] = response.get("Buckets", [])
            elif service == "lambda":
                response = _client(session, "lambda", state).list_functions()
                inventory["services"]["lambda"] = response.get("Functions", [])
            elif service == "rds":
                response = _client(session, "rds", state).describe_db_instances()
                inventory["services"]["rds"] = response.get("DBInstances", [])
            elif service == "iam":
                response = _client(session, "iam", state).list_roles()
                inventory["services"]["iam"] = response.get("Roles", [])
            else:
                inventory["services"][service] = {"error": f"Unsupported inventory service: {service}"}
        except Exception as exc:
            inventory["services"][service] = {"error": str(exc)}

    summary = llm_text(
        f"Summarize this AWS inventory, call out important resources, obvious risks, and likely next actions:\n\n{json.dumps(inventory, indent=2, ensure_ascii=False, default=_aws_json_default)[:25000]}"
    )
    _write_outputs("aws_inventory_agent", call_number, summary, inventory)
    state["aws_inventory"] = inventory
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "aws_inventory_agent",
        summary,
        f"aws_inventory_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def aws_cost_agent(state):
    _, task_content, _ = begin_agent_session(state, "aws_cost_agent")
    _require_aws_authorization(state)
    state["aws_cost_calls"] = state.get("aws_cost_calls", 0) + 1
    call_number = state["aws_cost_calls"]

    session = _get_boto3_session(state)
    ce = _client(session, "ce", state)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=int(state.get("aws_cost_days", 30)))
    granularity = state.get("aws_cost_granularity", "MONTHLY")
    metrics = state.get("aws_cost_metrics") or ["UnblendedCost"]
    group_by = state.get("aws_cost_group_by") or [{"Type": "DIMENSION", "Key": "SERVICE"}]

    payload = ce.get_cost_and_usage(
        TimePeriod={"Start": start_date.isoformat(), "End": end_date.isoformat()},
        Granularity=granularity,
        Metrics=metrics,
        GroupBy=group_by,
    )
    summary = llm_text(
        f"Summarize this AWS cost report, identify spend drivers, anomalies, and optimization opportunities:\n\n{json.dumps(payload, indent=2, ensure_ascii=False, default=_aws_json_default)[:25000]}"
    )
    _write_outputs("aws_cost_agent", call_number, summary, payload)
    state["aws_cost_report"] = payload
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "aws_cost_agent",
        summary,
        f"aws_cost_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )


def aws_automation_agent(state):
    _, task_content, _ = begin_agent_session(state, "aws_automation_agent")
    _require_aws_authorization(state)
    state["aws_automation_calls"] = state.get("aws_automation_calls", 0) + 1
    call_number = state["aws_automation_calls"]

    session = _get_boto3_session(state)
    operations = state.get("aws_operations")
    if not operations:
        service = state.get("aws_service")
        operation = state.get("aws_operation")
        parameters = state.get("aws_parameters", {})
        if not (service and operation):
            raise ValueError("aws_automation_agent requires 'aws_operations' or 'aws_service' + 'aws_operation'.")
        operations = [{"service": service, "operation": operation, "parameters": parameters}]

    results = []
    for item in operations:
        service = item.get("service", "")
        operation = item.get("operation", "")
        parameters = item.get("parameters", {}) or {}
        try:
            response = _execute_allowed_operation(session, service, operation, parameters, state)
            results.append(
                {
                    "service": service,
                    "operation": operation,
                    "parameters": parameters,
                    "status": "success",
                    "response": response,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "service": service,
                    "operation": operation,
                    "parameters": parameters,
                    "status": "error",
                    "error": str(exc),
                }
            )

    payload = {
        "request": task_content or state.get("current_objective") or state.get("user_query", ""),
        "allow_mutation": bool(state.get("aws_allow_mutation", False)),
        "results": results,
    }
    summary = llm_text(
        f"Summarize these AWS automation results. State what succeeded, what failed, and what to do next:\n\n{json.dumps(payload, indent=2, ensure_ascii=False, default=_aws_json_default)[:25000]}"
    )
    _write_outputs("aws_automation_agent", call_number, summary, payload)
    state["aws_automation_results"] = payload
    state["draft_response"] = summary
    log_task_update("AWS Automation", f"AWS automation pass #{call_number} saved to {OUTPUT_DIR}/aws_automation_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "aws_automation_agent",
        summary,
        f"aws_automation_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )
