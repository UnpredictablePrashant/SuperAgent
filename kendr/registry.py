from __future__ import annotations

from collections import OrderedDict

from tasks.a2a_protocol import make_agent_card

from .types import AgentDefinition, ChannelDefinition, PluginDefinition, ProviderDefinition


class Registry:
    def __init__(self) -> None:
        self.agents: "OrderedDict[str, AgentDefinition]" = OrderedDict()
        self.channels: "OrderedDict[str, ChannelDefinition]" = OrderedDict()
        self.providers: "OrderedDict[str, ProviderDefinition]" = OrderedDict()
        self.plugins: "OrderedDict[str, PluginDefinition]" = OrderedDict()

    def register_plugin(self, plugin: PluginDefinition) -> PluginDefinition:
        self.plugins[plugin.name] = plugin
        return plugin

    def register_agent(self, agent: AgentDefinition) -> AgentDefinition:
        self.agents[agent.name] = agent
        return agent

    def register_channel(self, channel: ChannelDefinition) -> ChannelDefinition:
        self.channels[channel.name] = channel
        return channel

    def register_provider(self, provider: ProviderDefinition) -> ProviderDefinition:
        self.providers[provider.name] = provider
        return provider

    def agent_cards(self) -> list[dict]:
        cards = []
        for agent in self.agents.values():
            cards.append(
                make_agent_card(
                    agent.name,
                    agent.description,
                    agent.skills,
                    agent.input_keys,
                    agent.output_keys,
                    agent.requirements,
                )
            )
        return cards

    def agent_descriptions(self) -> dict[str, str]:
        return {agent.name: agent.description for agent in self.agents.values()}
