function getDefaultExportFromCjs(x2) {
  return x2 && x2.__esModule && Object.prototype.hasOwnProperty.call(x2, "default") ? x2["default"] : x2;
}
var jsxRuntime = { exports: {} };
var reactJsxRuntime_production_min = {};
var react = { exports: {} };
var react_production_min = {};
/**
 * @license React
 * react.production.min.js
 *
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */
var l$2 = Symbol.for("react.element"), n$1 = Symbol.for("react.portal"), p$2 = Symbol.for("react.fragment"), q$1 = Symbol.for("react.strict_mode"), r = Symbol.for("react.profiler"), t = Symbol.for("react.provider"), u = Symbol.for("react.context"), v$2 = Symbol.for("react.forward_ref"), w = Symbol.for("react.suspense"), x = Symbol.for("react.memo"), y = Symbol.for("react.lazy"), z$1 = Symbol.iterator;
function A$1(a) {
  if (null === a || "object" !== typeof a) return null;
  a = z$1 && a[z$1] || a["@@iterator"];
  return "function" === typeof a ? a : null;
}
var B$1 = { isMounted: function() {
  return false;
}, enqueueForceUpdate: function() {
}, enqueueReplaceState: function() {
}, enqueueSetState: function() {
} }, C$1 = Object.assign, D$2 = {};
function E$1(a, b, e) {
  this.props = a;
  this.context = b;
  this.refs = D$2;
  this.updater = e || B$1;
}
E$1.prototype.isReactComponent = {};
E$1.prototype.setState = function(a, b) {
  if ("object" !== typeof a && "function" !== typeof a && null != a) throw Error("setState(...): takes an object of state variables to update or a function which returns an object of state variables.");
  this.updater.enqueueSetState(this, a, b, "setState");
};
E$1.prototype.forceUpdate = function(a) {
  this.updater.enqueueForceUpdate(this, a, "forceUpdate");
};
function F() {
}
F.prototype = E$1.prototype;
function G$1(a, b, e) {
  this.props = a;
  this.context = b;
  this.refs = D$2;
  this.updater = e || B$1;
}
var H$2 = G$1.prototype = new F();
H$2.constructor = G$1;
C$1(H$2, E$1.prototype);
H$2.isPureReactComponent = true;
var I$1 = Array.isArray, J = Object.prototype.hasOwnProperty, K$1 = { current: null }, L$1 = { key: true, ref: true, __self: true, __source: true };
function M$1(a, b, e) {
  var d, c = {}, k2 = null, h2 = null;
  if (null != b) for (d in void 0 !== b.ref && (h2 = b.ref), void 0 !== b.key && (k2 = "" + b.key), b) J.call(b, d) && !L$1.hasOwnProperty(d) && (c[d] = b[d]);
  var g = arguments.length - 2;
  if (1 === g) c.children = e;
  else if (1 < g) {
    for (var f2 = Array(g), m2 = 0; m2 < g; m2++) f2[m2] = arguments[m2 + 2];
    c.children = f2;
  }
  if (a && a.defaultProps) for (d in g = a.defaultProps, g) void 0 === c[d] && (c[d] = g[d]);
  return { $$typeof: l$2, type: a, key: k2, ref: h2, props: c, _owner: K$1.current };
}
function N$1(a, b) {
  return { $$typeof: l$2, type: a.type, key: b, ref: a.ref, props: a.props, _owner: a._owner };
}
function O$1(a) {
  return "object" === typeof a && null !== a && a.$$typeof === l$2;
}
function escape(a) {
  var b = { "=": "=0", ":": "=2" };
  return "$" + a.replace(/[=:]/g, function(a2) {
    return b[a2];
  });
}
var P$1 = /\/+/g;
function Q$1(a, b) {
  return "object" === typeof a && null !== a && null != a.key ? escape("" + a.key) : b.toString(36);
}
function R$1(a, b, e, d, c) {
  var k2 = typeof a;
  if ("undefined" === k2 || "boolean" === k2) a = null;
  var h2 = false;
  if (null === a) h2 = true;
  else switch (k2) {
    case "string":
    case "number":
      h2 = true;
      break;
    case "object":
      switch (a.$$typeof) {
        case l$2:
        case n$1:
          h2 = true;
      }
  }
  if (h2) return h2 = a, c = c(h2), a = "" === d ? "." + Q$1(h2, 0) : d, I$1(c) ? (e = "", null != a && (e = a.replace(P$1, "$&/") + "/"), R$1(c, b, e, "", function(a2) {
    return a2;
  })) : null != c && (O$1(c) && (c = N$1(c, e + (!c.key || h2 && h2.key === c.key ? "" : ("" + c.key).replace(P$1, "$&/") + "/") + a)), b.push(c)), 1;
  h2 = 0;
  d = "" === d ? "." : d + ":";
  if (I$1(a)) for (var g = 0; g < a.length; g++) {
    k2 = a[g];
    var f2 = d + Q$1(k2, g);
    h2 += R$1(k2, b, e, f2, c);
  }
  else if (f2 = A$1(a), "function" === typeof f2) for (a = f2.call(a), g = 0; !(k2 = a.next()).done; ) k2 = k2.value, f2 = d + Q$1(k2, g++), h2 += R$1(k2, b, e, f2, c);
  else if ("object" === k2) throw b = String(a), Error("Objects are not valid as a React child (found: " + ("[object Object]" === b ? "object with keys {" + Object.keys(a).join(", ") + "}" : b) + "). If you meant to render a collection of children, use an array instead.");
  return h2;
}
function S$1(a, b, e) {
  if (null == a) return a;
  var d = [], c = 0;
  R$1(a, d, "", "", function(a2) {
    return b.call(e, a2, c++);
  });
  return d;
}
function T$1(a) {
  if (-1 === a._status) {
    var b = a._result;
    b = b();
    b.then(function(b2) {
      if (0 === a._status || -1 === a._status) a._status = 1, a._result = b2;
    }, function(b2) {
      if (0 === a._status || -1 === a._status) a._status = 2, a._result = b2;
    });
    -1 === a._status && (a._status = 0, a._result = b);
  }
  if (1 === a._status) return a._result.default;
  throw a._result;
}
var U$1 = { current: null }, V$1 = { transition: null }, W$1 = { ReactCurrentDispatcher: U$1, ReactCurrentBatchConfig: V$1, ReactCurrentOwner: K$1 };
function X$1() {
  throw Error("act(...) is not supported in production builds of React.");
}
react_production_min.Children = { map: S$1, forEach: function(a, b, e) {
  S$1(a, function() {
    b.apply(this, arguments);
  }, e);
}, count: function(a) {
  var b = 0;
  S$1(a, function() {
    b++;
  });
  return b;
}, toArray: function(a) {
  return S$1(a, function(a2) {
    return a2;
  }) || [];
}, only: function(a) {
  if (!O$1(a)) throw Error("React.Children.only expected to receive a single React element child.");
  return a;
} };
react_production_min.Component = E$1;
react_production_min.Fragment = p$2;
react_production_min.Profiler = r;
react_production_min.PureComponent = G$1;
react_production_min.StrictMode = q$1;
react_production_min.Suspense = w;
react_production_min.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED = W$1;
react_production_min.act = X$1;
react_production_min.cloneElement = function(a, b, e) {
  if (null === a || void 0 === a) throw Error("React.cloneElement(...): The argument must be a React element, but you passed " + a + ".");
  var d = C$1({}, a.props), c = a.key, k2 = a.ref, h2 = a._owner;
  if (null != b) {
    void 0 !== b.ref && (k2 = b.ref, h2 = K$1.current);
    void 0 !== b.key && (c = "" + b.key);
    if (a.type && a.type.defaultProps) var g = a.type.defaultProps;
    for (f2 in b) J.call(b, f2) && !L$1.hasOwnProperty(f2) && (d[f2] = void 0 === b[f2] && void 0 !== g ? g[f2] : b[f2]);
  }
  var f2 = arguments.length - 2;
  if (1 === f2) d.children = e;
  else if (1 < f2) {
    g = Array(f2);
    for (var m2 = 0; m2 < f2; m2++) g[m2] = arguments[m2 + 2];
    d.children = g;
  }
  return { $$typeof: l$2, type: a.type, key: c, ref: k2, props: d, _owner: h2 };
};
react_production_min.createContext = function(a) {
  a = { $$typeof: u, _currentValue: a, _currentValue2: a, _threadCount: 0, Provider: null, Consumer: null, _defaultValue: null, _globalName: null };
  a.Provider = { $$typeof: t, _context: a };
  return a.Consumer = a;
};
react_production_min.createElement = M$1;
react_production_min.createFactory = function(a) {
  var b = M$1.bind(null, a);
  b.type = a;
  return b;
};
react_production_min.createRef = function() {
  return { current: null };
};
react_production_min.forwardRef = function(a) {
  return { $$typeof: v$2, render: a };
};
react_production_min.isValidElement = O$1;
react_production_min.lazy = function(a) {
  return { $$typeof: y, _payload: { _status: -1, _result: a }, _init: T$1 };
};
react_production_min.memo = function(a, b) {
  return { $$typeof: x, type: a, compare: void 0 === b ? null : b };
};
react_production_min.startTransition = function(a) {
  var b = V$1.transition;
  V$1.transition = {};
  try {
    a();
  } finally {
    V$1.transition = b;
  }
};
react_production_min.unstable_act = X$1;
react_production_min.useCallback = function(a, b) {
  return U$1.current.useCallback(a, b);
};
react_production_min.useContext = function(a) {
  return U$1.current.useContext(a);
};
react_production_min.useDebugValue = function() {
};
react_production_min.useDeferredValue = function(a) {
  return U$1.current.useDeferredValue(a);
};
react_production_min.useEffect = function(a, b) {
  return U$1.current.useEffect(a, b);
};
react_production_min.useId = function() {
  return U$1.current.useId();
};
react_production_min.useImperativeHandle = function(a, b, e) {
  return U$1.current.useImperativeHandle(a, b, e);
};
react_production_min.useInsertionEffect = function(a, b) {
  return U$1.current.useInsertionEffect(a, b);
};
react_production_min.useLayoutEffect = function(a, b) {
  return U$1.current.useLayoutEffect(a, b);
};
react_production_min.useMemo = function(a, b) {
  return U$1.current.useMemo(a, b);
};
react_production_min.useReducer = function(a, b, e) {
  return U$1.current.useReducer(a, b, e);
};
react_production_min.useRef = function(a) {
  return U$1.current.useRef(a);
};
react_production_min.useState = function(a) {
  return U$1.current.useState(a);
};
react_production_min.useSyncExternalStore = function(a, b, e) {
  return U$1.current.useSyncExternalStore(a, b, e);
};
react_production_min.useTransition = function() {
  return U$1.current.useTransition();
};
react_production_min.version = "18.3.1";
{
  react.exports = react_production_min;
}
var reactExports = react.exports;
const React = /* @__PURE__ */ getDefaultExportFromCjs(reactExports);
/**
 * @license React
 * react-jsx-runtime.production.min.js
 *
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */
var f = reactExports, k$1 = Symbol.for("react.element"), l$1 = Symbol.for("react.fragment"), m$1 = Object.prototype.hasOwnProperty, n = f.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentOwner, p$1 = { key: true, ref: true, __self: true, __source: true };
function q(c, a, g) {
  var b, d = {}, e = null, h2 = null;
  void 0 !== g && (e = "" + g);
  void 0 !== a.key && (e = "" + a.key);
  void 0 !== a.ref && (h2 = a.ref);
  for (b in a) m$1.call(a, b) && !p$1.hasOwnProperty(b) && (d[b] = a[b]);
  if (c && c.defaultProps) for (b in a = c.defaultProps, a) void 0 === d[b] && (d[b] = a[b]);
  return { $$typeof: k$1, type: c, key: e, ref: h2, props: d, _owner: n.current };
}
reactJsxRuntime_production_min.Fragment = l$1;
reactJsxRuntime_production_min.jsx = q;
reactJsxRuntime_production_min.jsxs = q;
{
  jsxRuntime.exports = reactJsxRuntime_production_min;
}
var jsxRuntimeExports = jsxRuntime.exports;
var client = {};
var reactDom = { exports: {} };
var reactDom_production_min = {};
var scheduler = { exports: {} };
var scheduler_production_min = {};
/**
 * @license React
 * scheduler.production.min.js
 *
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */
(function(exports$1) {
  function f2(a, b) {
    var c = a.length;
    a.push(b);
    a: for (; 0 < c; ) {
      var d = c - 1 >>> 1, e = a[d];
      if (0 < g(e, b)) a[d] = b, a[c] = e, c = d;
      else break a;
    }
  }
  function h2(a) {
    return 0 === a.length ? null : a[0];
  }
  function k2(a) {
    if (0 === a.length) return null;
    var b = a[0], c = a.pop();
    if (c !== b) {
      a[0] = c;
      a: for (var d = 0, e = a.length, w2 = e >>> 1; d < w2; ) {
        var m2 = 2 * (d + 1) - 1, C2 = a[m2], n2 = m2 + 1, x2 = a[n2];
        if (0 > g(C2, c)) n2 < e && 0 > g(x2, C2) ? (a[d] = x2, a[n2] = c, d = n2) : (a[d] = C2, a[m2] = c, d = m2);
        else if (n2 < e && 0 > g(x2, c)) a[d] = x2, a[n2] = c, d = n2;
        else break a;
      }
    }
    return b;
  }
  function g(a, b) {
    var c = a.sortIndex - b.sortIndex;
    return 0 !== c ? c : a.id - b.id;
  }
  if ("object" === typeof performance && "function" === typeof performance.now) {
    var l2 = performance;
    exports$1.unstable_now = function() {
      return l2.now();
    };
  } else {
    var p2 = Date, q2 = p2.now();
    exports$1.unstable_now = function() {
      return p2.now() - q2;
    };
  }
  var r2 = [], t2 = [], u2 = 1, v2 = null, y2 = 3, z2 = false, A2 = false, B2 = false, D2 = "function" === typeof setTimeout ? setTimeout : null, E2 = "function" === typeof clearTimeout ? clearTimeout : null, F2 = "undefined" !== typeof setImmediate ? setImmediate : null;
  "undefined" !== typeof navigator && void 0 !== navigator.scheduling && void 0 !== navigator.scheduling.isInputPending && navigator.scheduling.isInputPending.bind(navigator.scheduling);
  function G2(a) {
    for (var b = h2(t2); null !== b; ) {
      if (null === b.callback) k2(t2);
      else if (b.startTime <= a) k2(t2), b.sortIndex = b.expirationTime, f2(r2, b);
      else break;
      b = h2(t2);
    }
  }
  function H2(a) {
    B2 = false;
    G2(a);
    if (!A2) if (null !== h2(r2)) A2 = true, I2(J2);
    else {
      var b = h2(t2);
      null !== b && K2(H2, b.startTime - a);
    }
  }
  function J2(a, b) {
    A2 = false;
    B2 && (B2 = false, E2(L2), L2 = -1);
    z2 = true;
    var c = y2;
    try {
      G2(b);
      for (v2 = h2(r2); null !== v2 && (!(v2.expirationTime > b) || a && !M2()); ) {
        var d = v2.callback;
        if ("function" === typeof d) {
          v2.callback = null;
          y2 = v2.priorityLevel;
          var e = d(v2.expirationTime <= b);
          b = exports$1.unstable_now();
          "function" === typeof e ? v2.callback = e : v2 === h2(r2) && k2(r2);
          G2(b);
        } else k2(r2);
        v2 = h2(r2);
      }
      if (null !== v2) var w2 = true;
      else {
        var m2 = h2(t2);
        null !== m2 && K2(H2, m2.startTime - b);
        w2 = false;
      }
      return w2;
    } finally {
      v2 = null, y2 = c, z2 = false;
    }
  }
  var N2 = false, O2 = null, L2 = -1, P2 = 5, Q2 = -1;
  function M2() {
    return exports$1.unstable_now() - Q2 < P2 ? false : true;
  }
  function R2() {
    if (null !== O2) {
      var a = exports$1.unstable_now();
      Q2 = a;
      var b = true;
      try {
        b = O2(true, a);
      } finally {
        b ? S2() : (N2 = false, O2 = null);
      }
    } else N2 = false;
  }
  var S2;
  if ("function" === typeof F2) S2 = function() {
    F2(R2);
  };
  else if ("undefined" !== typeof MessageChannel) {
    var T2 = new MessageChannel(), U2 = T2.port2;
    T2.port1.onmessage = R2;
    S2 = function() {
      U2.postMessage(null);
    };
  } else S2 = function() {
    D2(R2, 0);
  };
  function I2(a) {
    O2 = a;
    N2 || (N2 = true, S2());
  }
  function K2(a, b) {
    L2 = D2(function() {
      a(exports$1.unstable_now());
    }, b);
  }
  exports$1.unstable_IdlePriority = 5;
  exports$1.unstable_ImmediatePriority = 1;
  exports$1.unstable_LowPriority = 4;
  exports$1.unstable_NormalPriority = 3;
  exports$1.unstable_Profiling = null;
  exports$1.unstable_UserBlockingPriority = 2;
  exports$1.unstable_cancelCallback = function(a) {
    a.callback = null;
  };
  exports$1.unstable_continueExecution = function() {
    A2 || z2 || (A2 = true, I2(J2));
  };
  exports$1.unstable_forceFrameRate = function(a) {
    0 > a || 125 < a ? console.error("forceFrameRate takes a positive int between 0 and 125, forcing frame rates higher than 125 fps is not supported") : P2 = 0 < a ? Math.floor(1e3 / a) : 5;
  };
  exports$1.unstable_getCurrentPriorityLevel = function() {
    return y2;
  };
  exports$1.unstable_getFirstCallbackNode = function() {
    return h2(r2);
  };
  exports$1.unstable_next = function(a) {
    switch (y2) {
      case 1:
      case 2:
      case 3:
        var b = 3;
        break;
      default:
        b = y2;
    }
    var c = y2;
    y2 = b;
    try {
      return a();
    } finally {
      y2 = c;
    }
  };
  exports$1.unstable_pauseExecution = function() {
  };
  exports$1.unstable_requestPaint = function() {
  };
  exports$1.unstable_runWithPriority = function(a, b) {
    switch (a) {
      case 1:
      case 2:
      case 3:
      case 4:
      case 5:
        break;
      default:
        a = 3;
    }
    var c = y2;
    y2 = a;
    try {
      return b();
    } finally {
      y2 = c;
    }
  };
  exports$1.unstable_scheduleCallback = function(a, b, c) {
    var d = exports$1.unstable_now();
    "object" === typeof c && null !== c ? (c = c.delay, c = "number" === typeof c && 0 < c ? d + c : d) : c = d;
    switch (a) {
      case 1:
        var e = -1;
        break;
      case 2:
        e = 250;
        break;
      case 5:
        e = 1073741823;
        break;
      case 4:
        e = 1e4;
        break;
      default:
        e = 5e3;
    }
    e = c + e;
    a = { id: u2++, callback: b, priorityLevel: a, startTime: c, expirationTime: e, sortIndex: -1 };
    c > d ? (a.sortIndex = c, f2(t2, a), null === h2(r2) && a === h2(t2) && (B2 ? (E2(L2), L2 = -1) : B2 = true, K2(H2, c - d))) : (a.sortIndex = e, f2(r2, a), A2 || z2 || (A2 = true, I2(J2)));
    return a;
  };
  exports$1.unstable_shouldYield = M2;
  exports$1.unstable_wrapCallback = function(a) {
    var b = y2;
    return function() {
      var c = y2;
      y2 = b;
      try {
        return a.apply(this, arguments);
      } finally {
        y2 = c;
      }
    };
  };
})(scheduler_production_min);
{
  scheduler.exports = scheduler_production_min;
}
var schedulerExports = scheduler.exports;
/**
 * @license React
 * react-dom.production.min.js
 *
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */
var aa = reactExports, ca = schedulerExports;
function p(a) {
  for (var b = "https://reactjs.org/docs/error-decoder.html?invariant=" + a, c = 1; c < arguments.length; c++) b += "&args[]=" + encodeURIComponent(arguments[c]);
  return "Minified React error #" + a + "; visit " + b + " for the full message or use the non-minified dev environment for full errors and additional helpful warnings.";
}
var da = /* @__PURE__ */ new Set(), ea = {};
function fa(a, b) {
  ha(a, b);
  ha(a + "Capture", b);
}
function ha(a, b) {
  ea[a] = b;
  for (a = 0; a < b.length; a++) da.add(b[a]);
}
var ia = !("undefined" === typeof window || "undefined" === typeof window.document || "undefined" === typeof window.document.createElement), ja = Object.prototype.hasOwnProperty, ka = /^[:A-Z_a-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD][:A-Z_a-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD\-.0-9\u00B7\u0300-\u036F\u203F-\u2040]*$/, la = {}, ma = {};
function oa(a) {
  if (ja.call(ma, a)) return true;
  if (ja.call(la, a)) return false;
  if (ka.test(a)) return ma[a] = true;
  la[a] = true;
  return false;
}
function pa(a, b, c, d) {
  if (null !== c && 0 === c.type) return false;
  switch (typeof b) {
    case "function":
    case "symbol":
      return true;
    case "boolean":
      if (d) return false;
      if (null !== c) return !c.acceptsBooleans;
      a = a.toLowerCase().slice(0, 5);
      return "data-" !== a && "aria-" !== a;
    default:
      return false;
  }
}
function qa(a, b, c, d) {
  if (null === b || "undefined" === typeof b || pa(a, b, c, d)) return true;
  if (d) return false;
  if (null !== c) switch (c.type) {
    case 3:
      return !b;
    case 4:
      return false === b;
    case 5:
      return isNaN(b);
    case 6:
      return isNaN(b) || 1 > b;
  }
  return false;
}
function v$1(a, b, c, d, e, f2, g) {
  this.acceptsBooleans = 2 === b || 3 === b || 4 === b;
  this.attributeName = d;
  this.attributeNamespace = e;
  this.mustUseProperty = c;
  this.propertyName = a;
  this.type = b;
  this.sanitizeURL = f2;
  this.removeEmptyString = g;
}
var z = {};
"children dangerouslySetInnerHTML defaultValue defaultChecked innerHTML suppressContentEditableWarning suppressHydrationWarning style".split(" ").forEach(function(a) {
  z[a] = new v$1(a, 0, false, a, null, false, false);
});
[["acceptCharset", "accept-charset"], ["className", "class"], ["htmlFor", "for"], ["httpEquiv", "http-equiv"]].forEach(function(a) {
  var b = a[0];
  z[b] = new v$1(b, 1, false, a[1], null, false, false);
});
["contentEditable", "draggable", "spellCheck", "value"].forEach(function(a) {
  z[a] = new v$1(a, 2, false, a.toLowerCase(), null, false, false);
});
["autoReverse", "externalResourcesRequired", "focusable", "preserveAlpha"].forEach(function(a) {
  z[a] = new v$1(a, 2, false, a, null, false, false);
});
"allowFullScreen async autoFocus autoPlay controls default defer disabled disablePictureInPicture disableRemotePlayback formNoValidate hidden loop noModule noValidate open playsInline readOnly required reversed scoped seamless itemScope".split(" ").forEach(function(a) {
  z[a] = new v$1(a, 3, false, a.toLowerCase(), null, false, false);
});
["checked", "multiple", "muted", "selected"].forEach(function(a) {
  z[a] = new v$1(a, 3, true, a, null, false, false);
});
["capture", "download"].forEach(function(a) {
  z[a] = new v$1(a, 4, false, a, null, false, false);
});
["cols", "rows", "size", "span"].forEach(function(a) {
  z[a] = new v$1(a, 6, false, a, null, false, false);
});
["rowSpan", "start"].forEach(function(a) {
  z[a] = new v$1(a, 5, false, a.toLowerCase(), null, false, false);
});
var ra = /[\-:]([a-z])/g;
function sa(a) {
  return a[1].toUpperCase();
}
"accent-height alignment-baseline arabic-form baseline-shift cap-height clip-path clip-rule color-interpolation color-interpolation-filters color-profile color-rendering dominant-baseline enable-background fill-opacity fill-rule flood-color flood-opacity font-family font-size font-size-adjust font-stretch font-style font-variant font-weight glyph-name glyph-orientation-horizontal glyph-orientation-vertical horiz-adv-x horiz-origin-x image-rendering letter-spacing lighting-color marker-end marker-mid marker-start overline-position overline-thickness paint-order panose-1 pointer-events rendering-intent shape-rendering stop-color stop-opacity strikethrough-position strikethrough-thickness stroke-dasharray stroke-dashoffset stroke-linecap stroke-linejoin stroke-miterlimit stroke-opacity stroke-width text-anchor text-decoration text-rendering underline-position underline-thickness unicode-bidi unicode-range units-per-em v-alphabetic v-hanging v-ideographic v-mathematical vector-effect vert-adv-y vert-origin-x vert-origin-y word-spacing writing-mode xmlns:xlink x-height".split(" ").forEach(function(a) {
  var b = a.replace(
    ra,
    sa
  );
  z[b] = new v$1(b, 1, false, a, null, false, false);
});
"xlink:actuate xlink:arcrole xlink:role xlink:show xlink:title xlink:type".split(" ").forEach(function(a) {
  var b = a.replace(ra, sa);
  z[b] = new v$1(b, 1, false, a, "http://www.w3.org/1999/xlink", false, false);
});
["xml:base", "xml:lang", "xml:space"].forEach(function(a) {
  var b = a.replace(ra, sa);
  z[b] = new v$1(b, 1, false, a, "http://www.w3.org/XML/1998/namespace", false, false);
});
["tabIndex", "crossOrigin"].forEach(function(a) {
  z[a] = new v$1(a, 1, false, a.toLowerCase(), null, false, false);
});
z.xlinkHref = new v$1("xlinkHref", 1, false, "xlink:href", "http://www.w3.org/1999/xlink", true, false);
["src", "href", "action", "formAction"].forEach(function(a) {
  z[a] = new v$1(a, 1, false, a.toLowerCase(), null, true, true);
});
function ta(a, b, c, d) {
  var e = z.hasOwnProperty(b) ? z[b] : null;
  if (null !== e ? 0 !== e.type : d || !(2 < b.length) || "o" !== b[0] && "O" !== b[0] || "n" !== b[1] && "N" !== b[1]) qa(b, c, e, d) && (c = null), d || null === e ? oa(b) && (null === c ? a.removeAttribute(b) : a.setAttribute(b, "" + c)) : e.mustUseProperty ? a[e.propertyName] = null === c ? 3 === e.type ? false : "" : c : (b = e.attributeName, d = e.attributeNamespace, null === c ? a.removeAttribute(b) : (e = e.type, c = 3 === e || 4 === e && true === c ? "" : "" + c, d ? a.setAttributeNS(d, b, c) : a.setAttribute(b, c)));
}
var ua = aa.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED, va = Symbol.for("react.element"), wa = Symbol.for("react.portal"), ya = Symbol.for("react.fragment"), za = Symbol.for("react.strict_mode"), Aa = Symbol.for("react.profiler"), Ba = Symbol.for("react.provider"), Ca = Symbol.for("react.context"), Da = Symbol.for("react.forward_ref"), Ea = Symbol.for("react.suspense"), Fa = Symbol.for("react.suspense_list"), Ga = Symbol.for("react.memo"), Ha = Symbol.for("react.lazy");
var Ia = Symbol.for("react.offscreen");
var Ja = Symbol.iterator;
function Ka(a) {
  if (null === a || "object" !== typeof a) return null;
  a = Ja && a[Ja] || a["@@iterator"];
  return "function" === typeof a ? a : null;
}
var A = Object.assign, La;
function Ma(a) {
  if (void 0 === La) try {
    throw Error();
  } catch (c) {
    var b = c.stack.trim().match(/\n( *(at )?)/);
    La = b && b[1] || "";
  }
  return "\n" + La + a;
}
var Na = false;
function Oa(a, b) {
  if (!a || Na) return "";
  Na = true;
  var c = Error.prepareStackTrace;
  Error.prepareStackTrace = void 0;
  try {
    if (b) if (b = function() {
      throw Error();
    }, Object.defineProperty(b.prototype, "props", { set: function() {
      throw Error();
    } }), "object" === typeof Reflect && Reflect.construct) {
      try {
        Reflect.construct(b, []);
      } catch (l2) {
        var d = l2;
      }
      Reflect.construct(a, [], b);
    } else {
      try {
        b.call();
      } catch (l2) {
        d = l2;
      }
      a.call(b.prototype);
    }
    else {
      try {
        throw Error();
      } catch (l2) {
        d = l2;
      }
      a();
    }
  } catch (l2) {
    if (l2 && d && "string" === typeof l2.stack) {
      for (var e = l2.stack.split("\n"), f2 = d.stack.split("\n"), g = e.length - 1, h2 = f2.length - 1; 1 <= g && 0 <= h2 && e[g] !== f2[h2]; ) h2--;
      for (; 1 <= g && 0 <= h2; g--, h2--) if (e[g] !== f2[h2]) {
        if (1 !== g || 1 !== h2) {
          do
            if (g--, h2--, 0 > h2 || e[g] !== f2[h2]) {
              var k2 = "\n" + e[g].replace(" at new ", " at ");
              a.displayName && k2.includes("<anonymous>") && (k2 = k2.replace("<anonymous>", a.displayName));
              return k2;
            }
          while (1 <= g && 0 <= h2);
        }
        break;
      }
    }
  } finally {
    Na = false, Error.prepareStackTrace = c;
  }
  return (a = a ? a.displayName || a.name : "") ? Ma(a) : "";
}
function Pa(a) {
  switch (a.tag) {
    case 5:
      return Ma(a.type);
    case 16:
      return Ma("Lazy");
    case 13:
      return Ma("Suspense");
    case 19:
      return Ma("SuspenseList");
    case 0:
    case 2:
    case 15:
      return a = Oa(a.type, false), a;
    case 11:
      return a = Oa(a.type.render, false), a;
    case 1:
      return a = Oa(a.type, true), a;
    default:
      return "";
  }
}
function Qa(a) {
  if (null == a) return null;
  if ("function" === typeof a) return a.displayName || a.name || null;
  if ("string" === typeof a) return a;
  switch (a) {
    case ya:
      return "Fragment";
    case wa:
      return "Portal";
    case Aa:
      return "Profiler";
    case za:
      return "StrictMode";
    case Ea:
      return "Suspense";
    case Fa:
      return "SuspenseList";
  }
  if ("object" === typeof a) switch (a.$$typeof) {
    case Ca:
      return (a.displayName || "Context") + ".Consumer";
    case Ba:
      return (a._context.displayName || "Context") + ".Provider";
    case Da:
      var b = a.render;
      a = a.displayName;
      a || (a = b.displayName || b.name || "", a = "" !== a ? "ForwardRef(" + a + ")" : "ForwardRef");
      return a;
    case Ga:
      return b = a.displayName || null, null !== b ? b : Qa(a.type) || "Memo";
    case Ha:
      b = a._payload;
      a = a._init;
      try {
        return Qa(a(b));
      } catch (c) {
      }
  }
  return null;
}
function Ra(a) {
  var b = a.type;
  switch (a.tag) {
    case 24:
      return "Cache";
    case 9:
      return (b.displayName || "Context") + ".Consumer";
    case 10:
      return (b._context.displayName || "Context") + ".Provider";
    case 18:
      return "DehydratedFragment";
    case 11:
      return a = b.render, a = a.displayName || a.name || "", b.displayName || ("" !== a ? "ForwardRef(" + a + ")" : "ForwardRef");
    case 7:
      return "Fragment";
    case 5:
      return b;
    case 4:
      return "Portal";
    case 3:
      return "Root";
    case 6:
      return "Text";
    case 16:
      return Qa(b);
    case 8:
      return b === za ? "StrictMode" : "Mode";
    case 22:
      return "Offscreen";
    case 12:
      return "Profiler";
    case 21:
      return "Scope";
    case 13:
      return "Suspense";
    case 19:
      return "SuspenseList";
    case 25:
      return "TracingMarker";
    case 1:
    case 0:
    case 17:
    case 2:
    case 14:
    case 15:
      if ("function" === typeof b) return b.displayName || b.name || null;
      if ("string" === typeof b) return b;
  }
  return null;
}
function Sa(a) {
  switch (typeof a) {
    case "boolean":
    case "number":
    case "string":
    case "undefined":
      return a;
    case "object":
      return a;
    default:
      return "";
  }
}
function Ta(a) {
  var b = a.type;
  return (a = a.nodeName) && "input" === a.toLowerCase() && ("checkbox" === b || "radio" === b);
}
function Ua(a) {
  var b = Ta(a) ? "checked" : "value", c = Object.getOwnPropertyDescriptor(a.constructor.prototype, b), d = "" + a[b];
  if (!a.hasOwnProperty(b) && "undefined" !== typeof c && "function" === typeof c.get && "function" === typeof c.set) {
    var e = c.get, f2 = c.set;
    Object.defineProperty(a, b, { configurable: true, get: function() {
      return e.call(this);
    }, set: function(a2) {
      d = "" + a2;
      f2.call(this, a2);
    } });
    Object.defineProperty(a, b, { enumerable: c.enumerable });
    return { getValue: function() {
      return d;
    }, setValue: function(a2) {
      d = "" + a2;
    }, stopTracking: function() {
      a._valueTracker = null;
      delete a[b];
    } };
  }
}
function Va(a) {
  a._valueTracker || (a._valueTracker = Ua(a));
}
function Wa(a) {
  if (!a) return false;
  var b = a._valueTracker;
  if (!b) return true;
  var c = b.getValue();
  var d = "";
  a && (d = Ta(a) ? a.checked ? "true" : "false" : a.value);
  a = d;
  return a !== c ? (b.setValue(a), true) : false;
}
function Xa(a) {
  a = a || ("undefined" !== typeof document ? document : void 0);
  if ("undefined" === typeof a) return null;
  try {
    return a.activeElement || a.body;
  } catch (b) {
    return a.body;
  }
}
function Ya(a, b) {
  var c = b.checked;
  return A({}, b, { defaultChecked: void 0, defaultValue: void 0, value: void 0, checked: null != c ? c : a._wrapperState.initialChecked });
}
function Za(a, b) {
  var c = null == b.defaultValue ? "" : b.defaultValue, d = null != b.checked ? b.checked : b.defaultChecked;
  c = Sa(null != b.value ? b.value : c);
  a._wrapperState = { initialChecked: d, initialValue: c, controlled: "checkbox" === b.type || "radio" === b.type ? null != b.checked : null != b.value };
}
function ab(a, b) {
  b = b.checked;
  null != b && ta(a, "checked", b, false);
}
function bb(a, b) {
  ab(a, b);
  var c = Sa(b.value), d = b.type;
  if (null != c) if ("number" === d) {
    if (0 === c && "" === a.value || a.value != c) a.value = "" + c;
  } else a.value !== "" + c && (a.value = "" + c);
  else if ("submit" === d || "reset" === d) {
    a.removeAttribute("value");
    return;
  }
  b.hasOwnProperty("value") ? cb(a, b.type, c) : b.hasOwnProperty("defaultValue") && cb(a, b.type, Sa(b.defaultValue));
  null == b.checked && null != b.defaultChecked && (a.defaultChecked = !!b.defaultChecked);
}
function db(a, b, c) {
  if (b.hasOwnProperty("value") || b.hasOwnProperty("defaultValue")) {
    var d = b.type;
    if (!("submit" !== d && "reset" !== d || void 0 !== b.value && null !== b.value)) return;
    b = "" + a._wrapperState.initialValue;
    c || b === a.value || (a.value = b);
    a.defaultValue = b;
  }
  c = a.name;
  "" !== c && (a.name = "");
  a.defaultChecked = !!a._wrapperState.initialChecked;
  "" !== c && (a.name = c);
}
function cb(a, b, c) {
  if ("number" !== b || Xa(a.ownerDocument) !== a) null == c ? a.defaultValue = "" + a._wrapperState.initialValue : a.defaultValue !== "" + c && (a.defaultValue = "" + c);
}
var eb = Array.isArray;
function fb(a, b, c, d) {
  a = a.options;
  if (b) {
    b = {};
    for (var e = 0; e < c.length; e++) b["$" + c[e]] = true;
    for (c = 0; c < a.length; c++) e = b.hasOwnProperty("$" + a[c].value), a[c].selected !== e && (a[c].selected = e), e && d && (a[c].defaultSelected = true);
  } else {
    c = "" + Sa(c);
    b = null;
    for (e = 0; e < a.length; e++) {
      if (a[e].value === c) {
        a[e].selected = true;
        d && (a[e].defaultSelected = true);
        return;
      }
      null !== b || a[e].disabled || (b = a[e]);
    }
    null !== b && (b.selected = true);
  }
}
function gb(a, b) {
  if (null != b.dangerouslySetInnerHTML) throw Error(p(91));
  return A({}, b, { value: void 0, defaultValue: void 0, children: "" + a._wrapperState.initialValue });
}
function hb(a, b) {
  var c = b.value;
  if (null == c) {
    c = b.children;
    b = b.defaultValue;
    if (null != c) {
      if (null != b) throw Error(p(92));
      if (eb(c)) {
        if (1 < c.length) throw Error(p(93));
        c = c[0];
      }
      b = c;
    }
    null == b && (b = "");
    c = b;
  }
  a._wrapperState = { initialValue: Sa(c) };
}
function ib(a, b) {
  var c = Sa(b.value), d = Sa(b.defaultValue);
  null != c && (c = "" + c, c !== a.value && (a.value = c), null == b.defaultValue && a.defaultValue !== c && (a.defaultValue = c));
  null != d && (a.defaultValue = "" + d);
}
function jb(a) {
  var b = a.textContent;
  b === a._wrapperState.initialValue && "" !== b && null !== b && (a.value = b);
}
function kb(a) {
  switch (a) {
    case "svg":
      return "http://www.w3.org/2000/svg";
    case "math":
      return "http://www.w3.org/1998/Math/MathML";
    default:
      return "http://www.w3.org/1999/xhtml";
  }
}
function lb(a, b) {
  return null == a || "http://www.w3.org/1999/xhtml" === a ? kb(b) : "http://www.w3.org/2000/svg" === a && "foreignObject" === b ? "http://www.w3.org/1999/xhtml" : a;
}
var mb, nb = function(a) {
  return "undefined" !== typeof MSApp && MSApp.execUnsafeLocalFunction ? function(b, c, d, e) {
    MSApp.execUnsafeLocalFunction(function() {
      return a(b, c, d, e);
    });
  } : a;
}(function(a, b) {
  if ("http://www.w3.org/2000/svg" !== a.namespaceURI || "innerHTML" in a) a.innerHTML = b;
  else {
    mb = mb || document.createElement("div");
    mb.innerHTML = "<svg>" + b.valueOf().toString() + "</svg>";
    for (b = mb.firstChild; a.firstChild; ) a.removeChild(a.firstChild);
    for (; b.firstChild; ) a.appendChild(b.firstChild);
  }
});
function ob(a, b) {
  if (b) {
    var c = a.firstChild;
    if (c && c === a.lastChild && 3 === c.nodeType) {
      c.nodeValue = b;
      return;
    }
  }
  a.textContent = b;
}
var pb = {
  animationIterationCount: true,
  aspectRatio: true,
  borderImageOutset: true,
  borderImageSlice: true,
  borderImageWidth: true,
  boxFlex: true,
  boxFlexGroup: true,
  boxOrdinalGroup: true,
  columnCount: true,
  columns: true,
  flex: true,
  flexGrow: true,
  flexPositive: true,
  flexShrink: true,
  flexNegative: true,
  flexOrder: true,
  gridArea: true,
  gridRow: true,
  gridRowEnd: true,
  gridRowSpan: true,
  gridRowStart: true,
  gridColumn: true,
  gridColumnEnd: true,
  gridColumnSpan: true,
  gridColumnStart: true,
  fontWeight: true,
  lineClamp: true,
  lineHeight: true,
  opacity: true,
  order: true,
  orphans: true,
  tabSize: true,
  widows: true,
  zIndex: true,
  zoom: true,
  fillOpacity: true,
  floodOpacity: true,
  stopOpacity: true,
  strokeDasharray: true,
  strokeDashoffset: true,
  strokeMiterlimit: true,
  strokeOpacity: true,
  strokeWidth: true
}, qb = ["Webkit", "ms", "Moz", "O"];
Object.keys(pb).forEach(function(a) {
  qb.forEach(function(b) {
    b = b + a.charAt(0).toUpperCase() + a.substring(1);
    pb[b] = pb[a];
  });
});
function rb(a, b, c) {
  return null == b || "boolean" === typeof b || "" === b ? "" : c || "number" !== typeof b || 0 === b || pb.hasOwnProperty(a) && pb[a] ? ("" + b).trim() : b + "px";
}
function sb(a, b) {
  a = a.style;
  for (var c in b) if (b.hasOwnProperty(c)) {
    var d = 0 === c.indexOf("--"), e = rb(c, b[c], d);
    "float" === c && (c = "cssFloat");
    d ? a.setProperty(c, e) : a[c] = e;
  }
}
var tb = A({ menuitem: true }, { area: true, base: true, br: true, col: true, embed: true, hr: true, img: true, input: true, keygen: true, link: true, meta: true, param: true, source: true, track: true, wbr: true });
function ub(a, b) {
  if (b) {
    if (tb[a] && (null != b.children || null != b.dangerouslySetInnerHTML)) throw Error(p(137, a));
    if (null != b.dangerouslySetInnerHTML) {
      if (null != b.children) throw Error(p(60));
      if ("object" !== typeof b.dangerouslySetInnerHTML || !("__html" in b.dangerouslySetInnerHTML)) throw Error(p(61));
    }
    if (null != b.style && "object" !== typeof b.style) throw Error(p(62));
  }
}
function vb(a, b) {
  if (-1 === a.indexOf("-")) return "string" === typeof b.is;
  switch (a) {
    case "annotation-xml":
    case "color-profile":
    case "font-face":
    case "font-face-src":
    case "font-face-uri":
    case "font-face-format":
    case "font-face-name":
    case "missing-glyph":
      return false;
    default:
      return true;
  }
}
var wb = null;
function xb(a) {
  a = a.target || a.srcElement || window;
  a.correspondingUseElement && (a = a.correspondingUseElement);
  return 3 === a.nodeType ? a.parentNode : a;
}
var yb = null, zb = null, Ab = null;
function Bb(a) {
  if (a = Cb(a)) {
    if ("function" !== typeof yb) throw Error(p(280));
    var b = a.stateNode;
    b && (b = Db(b), yb(a.stateNode, a.type, b));
  }
}
function Eb(a) {
  zb ? Ab ? Ab.push(a) : Ab = [a] : zb = a;
}
function Fb() {
  if (zb) {
    var a = zb, b = Ab;
    Ab = zb = null;
    Bb(a);
    if (b) for (a = 0; a < b.length; a++) Bb(b[a]);
  }
}
function Gb(a, b) {
  return a(b);
}
function Hb() {
}
var Ib = false;
function Jb(a, b, c) {
  if (Ib) return a(b, c);
  Ib = true;
  try {
    return Gb(a, b, c);
  } finally {
    if (Ib = false, null !== zb || null !== Ab) Hb(), Fb();
  }
}
function Kb(a, b) {
  var c = a.stateNode;
  if (null === c) return null;
  var d = Db(c);
  if (null === d) return null;
  c = d[b];
  a: switch (b) {
    case "onClick":
    case "onClickCapture":
    case "onDoubleClick":
    case "onDoubleClickCapture":
    case "onMouseDown":
    case "onMouseDownCapture":
    case "onMouseMove":
    case "onMouseMoveCapture":
    case "onMouseUp":
    case "onMouseUpCapture":
    case "onMouseEnter":
      (d = !d.disabled) || (a = a.type, d = !("button" === a || "input" === a || "select" === a || "textarea" === a));
      a = !d;
      break a;
    default:
      a = false;
  }
  if (a) return null;
  if (c && "function" !== typeof c) throw Error(p(231, b, typeof c));
  return c;
}
var Lb = false;
if (ia) try {
  var Mb = {};
  Object.defineProperty(Mb, "passive", { get: function() {
    Lb = true;
  } });
  window.addEventListener("test", Mb, Mb);
  window.removeEventListener("test", Mb, Mb);
} catch (a) {
  Lb = false;
}
function Nb(a, b, c, d, e, f2, g, h2, k2) {
  var l2 = Array.prototype.slice.call(arguments, 3);
  try {
    b.apply(c, l2);
  } catch (m2) {
    this.onError(m2);
  }
}
var Ob = false, Pb = null, Qb = false, Rb = null, Sb = { onError: function(a) {
  Ob = true;
  Pb = a;
} };
function Tb(a, b, c, d, e, f2, g, h2, k2) {
  Ob = false;
  Pb = null;
  Nb.apply(Sb, arguments);
}
function Ub(a, b, c, d, e, f2, g, h2, k2) {
  Tb.apply(this, arguments);
  if (Ob) {
    if (Ob) {
      var l2 = Pb;
      Ob = false;
      Pb = null;
    } else throw Error(p(198));
    Qb || (Qb = true, Rb = l2);
  }
}
function Vb(a) {
  var b = a, c = a;
  if (a.alternate) for (; b.return; ) b = b.return;
  else {
    a = b;
    do
      b = a, 0 !== (b.flags & 4098) && (c = b.return), a = b.return;
    while (a);
  }
  return 3 === b.tag ? c : null;
}
function Wb(a) {
  if (13 === a.tag) {
    var b = a.memoizedState;
    null === b && (a = a.alternate, null !== a && (b = a.memoizedState));
    if (null !== b) return b.dehydrated;
  }
  return null;
}
function Xb(a) {
  if (Vb(a) !== a) throw Error(p(188));
}
function Yb(a) {
  var b = a.alternate;
  if (!b) {
    b = Vb(a);
    if (null === b) throw Error(p(188));
    return b !== a ? null : a;
  }
  for (var c = a, d = b; ; ) {
    var e = c.return;
    if (null === e) break;
    var f2 = e.alternate;
    if (null === f2) {
      d = e.return;
      if (null !== d) {
        c = d;
        continue;
      }
      break;
    }
    if (e.child === f2.child) {
      for (f2 = e.child; f2; ) {
        if (f2 === c) return Xb(e), a;
        if (f2 === d) return Xb(e), b;
        f2 = f2.sibling;
      }
      throw Error(p(188));
    }
    if (c.return !== d.return) c = e, d = f2;
    else {
      for (var g = false, h2 = e.child; h2; ) {
        if (h2 === c) {
          g = true;
          c = e;
          d = f2;
          break;
        }
        if (h2 === d) {
          g = true;
          d = e;
          c = f2;
          break;
        }
        h2 = h2.sibling;
      }
      if (!g) {
        for (h2 = f2.child; h2; ) {
          if (h2 === c) {
            g = true;
            c = f2;
            d = e;
            break;
          }
          if (h2 === d) {
            g = true;
            d = f2;
            c = e;
            break;
          }
          h2 = h2.sibling;
        }
        if (!g) throw Error(p(189));
      }
    }
    if (c.alternate !== d) throw Error(p(190));
  }
  if (3 !== c.tag) throw Error(p(188));
  return c.stateNode.current === c ? a : b;
}
function Zb(a) {
  a = Yb(a);
  return null !== a ? $b(a) : null;
}
function $b(a) {
  if (5 === a.tag || 6 === a.tag) return a;
  for (a = a.child; null !== a; ) {
    var b = $b(a);
    if (null !== b) return b;
    a = a.sibling;
  }
  return null;
}
var ac = ca.unstable_scheduleCallback, bc = ca.unstable_cancelCallback, cc = ca.unstable_shouldYield, dc = ca.unstable_requestPaint, B = ca.unstable_now, ec = ca.unstable_getCurrentPriorityLevel, fc = ca.unstable_ImmediatePriority, gc = ca.unstable_UserBlockingPriority, hc = ca.unstable_NormalPriority, ic = ca.unstable_LowPriority, jc = ca.unstable_IdlePriority, kc = null, lc = null;
function mc(a) {
  if (lc && "function" === typeof lc.onCommitFiberRoot) try {
    lc.onCommitFiberRoot(kc, a, void 0, 128 === (a.current.flags & 128));
  } catch (b) {
  }
}
var oc = Math.clz32 ? Math.clz32 : nc, pc = Math.log, qc = Math.LN2;
function nc(a) {
  a >>>= 0;
  return 0 === a ? 32 : 31 - (pc(a) / qc | 0) | 0;
}
var rc = 64, sc = 4194304;
function tc(a) {
  switch (a & -a) {
    case 1:
      return 1;
    case 2:
      return 2;
    case 4:
      return 4;
    case 8:
      return 8;
    case 16:
      return 16;
    case 32:
      return 32;
    case 64:
    case 128:
    case 256:
    case 512:
    case 1024:
    case 2048:
    case 4096:
    case 8192:
    case 16384:
    case 32768:
    case 65536:
    case 131072:
    case 262144:
    case 524288:
    case 1048576:
    case 2097152:
      return a & 4194240;
    case 4194304:
    case 8388608:
    case 16777216:
    case 33554432:
    case 67108864:
      return a & 130023424;
    case 134217728:
      return 134217728;
    case 268435456:
      return 268435456;
    case 536870912:
      return 536870912;
    case 1073741824:
      return 1073741824;
    default:
      return a;
  }
}
function uc(a, b) {
  var c = a.pendingLanes;
  if (0 === c) return 0;
  var d = 0, e = a.suspendedLanes, f2 = a.pingedLanes, g = c & 268435455;
  if (0 !== g) {
    var h2 = g & ~e;
    0 !== h2 ? d = tc(h2) : (f2 &= g, 0 !== f2 && (d = tc(f2)));
  } else g = c & ~e, 0 !== g ? d = tc(g) : 0 !== f2 && (d = tc(f2));
  if (0 === d) return 0;
  if (0 !== b && b !== d && 0 === (b & e) && (e = d & -d, f2 = b & -b, e >= f2 || 16 === e && 0 !== (f2 & 4194240))) return b;
  0 !== (d & 4) && (d |= c & 16);
  b = a.entangledLanes;
  if (0 !== b) for (a = a.entanglements, b &= d; 0 < b; ) c = 31 - oc(b), e = 1 << c, d |= a[c], b &= ~e;
  return d;
}
function vc(a, b) {
  switch (a) {
    case 1:
    case 2:
    case 4:
      return b + 250;
    case 8:
    case 16:
    case 32:
    case 64:
    case 128:
    case 256:
    case 512:
    case 1024:
    case 2048:
    case 4096:
    case 8192:
    case 16384:
    case 32768:
    case 65536:
    case 131072:
    case 262144:
    case 524288:
    case 1048576:
    case 2097152:
      return b + 5e3;
    case 4194304:
    case 8388608:
    case 16777216:
    case 33554432:
    case 67108864:
      return -1;
    case 134217728:
    case 268435456:
    case 536870912:
    case 1073741824:
      return -1;
    default:
      return -1;
  }
}
function wc(a, b) {
  for (var c = a.suspendedLanes, d = a.pingedLanes, e = a.expirationTimes, f2 = a.pendingLanes; 0 < f2; ) {
    var g = 31 - oc(f2), h2 = 1 << g, k2 = e[g];
    if (-1 === k2) {
      if (0 === (h2 & c) || 0 !== (h2 & d)) e[g] = vc(h2, b);
    } else k2 <= b && (a.expiredLanes |= h2);
    f2 &= ~h2;
  }
}
function xc(a) {
  a = a.pendingLanes & -1073741825;
  return 0 !== a ? a : a & 1073741824 ? 1073741824 : 0;
}
function yc() {
  var a = rc;
  rc <<= 1;
  0 === (rc & 4194240) && (rc = 64);
  return a;
}
function zc(a) {
  for (var b = [], c = 0; 31 > c; c++) b.push(a);
  return b;
}
function Ac(a, b, c) {
  a.pendingLanes |= b;
  536870912 !== b && (a.suspendedLanes = 0, a.pingedLanes = 0);
  a = a.eventTimes;
  b = 31 - oc(b);
  a[b] = c;
}
function Bc(a, b) {
  var c = a.pendingLanes & ~b;
  a.pendingLanes = b;
  a.suspendedLanes = 0;
  a.pingedLanes = 0;
  a.expiredLanes &= b;
  a.mutableReadLanes &= b;
  a.entangledLanes &= b;
  b = a.entanglements;
  var d = a.eventTimes;
  for (a = a.expirationTimes; 0 < c; ) {
    var e = 31 - oc(c), f2 = 1 << e;
    b[e] = 0;
    d[e] = -1;
    a[e] = -1;
    c &= ~f2;
  }
}
function Cc(a, b) {
  var c = a.entangledLanes |= b;
  for (a = a.entanglements; c; ) {
    var d = 31 - oc(c), e = 1 << d;
    e & b | a[d] & b && (a[d] |= b);
    c &= ~e;
  }
}
var C = 0;
function Dc(a) {
  a &= -a;
  return 1 < a ? 4 < a ? 0 !== (a & 268435455) ? 16 : 536870912 : 4 : 1;
}
var Ec, Fc, Gc, Hc, Ic, Jc = false, Kc = [], Lc = null, Mc = null, Nc = null, Oc = /* @__PURE__ */ new Map(), Pc = /* @__PURE__ */ new Map(), Qc = [], Rc = "mousedown mouseup touchcancel touchend touchstart auxclick dblclick pointercancel pointerdown pointerup dragend dragstart drop compositionend compositionstart keydown keypress keyup input textInput copy cut paste click change contextmenu reset submit".split(" ");
function Sc(a, b) {
  switch (a) {
    case "focusin":
    case "focusout":
      Lc = null;
      break;
    case "dragenter":
    case "dragleave":
      Mc = null;
      break;
    case "mouseover":
    case "mouseout":
      Nc = null;
      break;
    case "pointerover":
    case "pointerout":
      Oc.delete(b.pointerId);
      break;
    case "gotpointercapture":
    case "lostpointercapture":
      Pc.delete(b.pointerId);
  }
}
function Tc(a, b, c, d, e, f2) {
  if (null === a || a.nativeEvent !== f2) return a = { blockedOn: b, domEventName: c, eventSystemFlags: d, nativeEvent: f2, targetContainers: [e] }, null !== b && (b = Cb(b), null !== b && Fc(b)), a;
  a.eventSystemFlags |= d;
  b = a.targetContainers;
  null !== e && -1 === b.indexOf(e) && b.push(e);
  return a;
}
function Uc(a, b, c, d, e) {
  switch (b) {
    case "focusin":
      return Lc = Tc(Lc, a, b, c, d, e), true;
    case "dragenter":
      return Mc = Tc(Mc, a, b, c, d, e), true;
    case "mouseover":
      return Nc = Tc(Nc, a, b, c, d, e), true;
    case "pointerover":
      var f2 = e.pointerId;
      Oc.set(f2, Tc(Oc.get(f2) || null, a, b, c, d, e));
      return true;
    case "gotpointercapture":
      return f2 = e.pointerId, Pc.set(f2, Tc(Pc.get(f2) || null, a, b, c, d, e)), true;
  }
  return false;
}
function Vc(a) {
  var b = Wc(a.target);
  if (null !== b) {
    var c = Vb(b);
    if (null !== c) {
      if (b = c.tag, 13 === b) {
        if (b = Wb(c), null !== b) {
          a.blockedOn = b;
          Ic(a.priority, function() {
            Gc(c);
          });
          return;
        }
      } else if (3 === b && c.stateNode.current.memoizedState.isDehydrated) {
        a.blockedOn = 3 === c.tag ? c.stateNode.containerInfo : null;
        return;
      }
    }
  }
  a.blockedOn = null;
}
function Xc(a) {
  if (null !== a.blockedOn) return false;
  for (var b = a.targetContainers; 0 < b.length; ) {
    var c = Yc(a.domEventName, a.eventSystemFlags, b[0], a.nativeEvent);
    if (null === c) {
      c = a.nativeEvent;
      var d = new c.constructor(c.type, c);
      wb = d;
      c.target.dispatchEvent(d);
      wb = null;
    } else return b = Cb(c), null !== b && Fc(b), a.blockedOn = c, false;
    b.shift();
  }
  return true;
}
function Zc(a, b, c) {
  Xc(a) && c.delete(b);
}
function $c() {
  Jc = false;
  null !== Lc && Xc(Lc) && (Lc = null);
  null !== Mc && Xc(Mc) && (Mc = null);
  null !== Nc && Xc(Nc) && (Nc = null);
  Oc.forEach(Zc);
  Pc.forEach(Zc);
}
function ad(a, b) {
  a.blockedOn === b && (a.blockedOn = null, Jc || (Jc = true, ca.unstable_scheduleCallback(ca.unstable_NormalPriority, $c)));
}
function bd(a) {
  function b(b2) {
    return ad(b2, a);
  }
  if (0 < Kc.length) {
    ad(Kc[0], a);
    for (var c = 1; c < Kc.length; c++) {
      var d = Kc[c];
      d.blockedOn === a && (d.blockedOn = null);
    }
  }
  null !== Lc && ad(Lc, a);
  null !== Mc && ad(Mc, a);
  null !== Nc && ad(Nc, a);
  Oc.forEach(b);
  Pc.forEach(b);
  for (c = 0; c < Qc.length; c++) d = Qc[c], d.blockedOn === a && (d.blockedOn = null);
  for (; 0 < Qc.length && (c = Qc[0], null === c.blockedOn); ) Vc(c), null === c.blockedOn && Qc.shift();
}
var cd = ua.ReactCurrentBatchConfig, dd = true;
function ed(a, b, c, d) {
  var e = C, f2 = cd.transition;
  cd.transition = null;
  try {
    C = 1, fd(a, b, c, d);
  } finally {
    C = e, cd.transition = f2;
  }
}
function gd(a, b, c, d) {
  var e = C, f2 = cd.transition;
  cd.transition = null;
  try {
    C = 4, fd(a, b, c, d);
  } finally {
    C = e, cd.transition = f2;
  }
}
function fd(a, b, c, d) {
  if (dd) {
    var e = Yc(a, b, c, d);
    if (null === e) hd(a, b, d, id, c), Sc(a, d);
    else if (Uc(e, a, b, c, d)) d.stopPropagation();
    else if (Sc(a, d), b & 4 && -1 < Rc.indexOf(a)) {
      for (; null !== e; ) {
        var f2 = Cb(e);
        null !== f2 && Ec(f2);
        f2 = Yc(a, b, c, d);
        null === f2 && hd(a, b, d, id, c);
        if (f2 === e) break;
        e = f2;
      }
      null !== e && d.stopPropagation();
    } else hd(a, b, d, null, c);
  }
}
var id = null;
function Yc(a, b, c, d) {
  id = null;
  a = xb(d);
  a = Wc(a);
  if (null !== a) if (b = Vb(a), null === b) a = null;
  else if (c = b.tag, 13 === c) {
    a = Wb(b);
    if (null !== a) return a;
    a = null;
  } else if (3 === c) {
    if (b.stateNode.current.memoizedState.isDehydrated) return 3 === b.tag ? b.stateNode.containerInfo : null;
    a = null;
  } else b !== a && (a = null);
  id = a;
  return null;
}
function jd(a) {
  switch (a) {
    case "cancel":
    case "click":
    case "close":
    case "contextmenu":
    case "copy":
    case "cut":
    case "auxclick":
    case "dblclick":
    case "dragend":
    case "dragstart":
    case "drop":
    case "focusin":
    case "focusout":
    case "input":
    case "invalid":
    case "keydown":
    case "keypress":
    case "keyup":
    case "mousedown":
    case "mouseup":
    case "paste":
    case "pause":
    case "play":
    case "pointercancel":
    case "pointerdown":
    case "pointerup":
    case "ratechange":
    case "reset":
    case "resize":
    case "seeked":
    case "submit":
    case "touchcancel":
    case "touchend":
    case "touchstart":
    case "volumechange":
    case "change":
    case "selectionchange":
    case "textInput":
    case "compositionstart":
    case "compositionend":
    case "compositionupdate":
    case "beforeblur":
    case "afterblur":
    case "beforeinput":
    case "blur":
    case "fullscreenchange":
    case "focus":
    case "hashchange":
    case "popstate":
    case "select":
    case "selectstart":
      return 1;
    case "drag":
    case "dragenter":
    case "dragexit":
    case "dragleave":
    case "dragover":
    case "mousemove":
    case "mouseout":
    case "mouseover":
    case "pointermove":
    case "pointerout":
    case "pointerover":
    case "scroll":
    case "toggle":
    case "touchmove":
    case "wheel":
    case "mouseenter":
    case "mouseleave":
    case "pointerenter":
    case "pointerleave":
      return 4;
    case "message":
      switch (ec()) {
        case fc:
          return 1;
        case gc:
          return 4;
        case hc:
        case ic:
          return 16;
        case jc:
          return 536870912;
        default:
          return 16;
      }
    default:
      return 16;
  }
}
var kd = null, ld = null, md = null;
function nd() {
  if (md) return md;
  var a, b = ld, c = b.length, d, e = "value" in kd ? kd.value : kd.textContent, f2 = e.length;
  for (a = 0; a < c && b[a] === e[a]; a++) ;
  var g = c - a;
  for (d = 1; d <= g && b[c - d] === e[f2 - d]; d++) ;
  return md = e.slice(a, 1 < d ? 1 - d : void 0);
}
function od(a) {
  var b = a.keyCode;
  "charCode" in a ? (a = a.charCode, 0 === a && 13 === b && (a = 13)) : a = b;
  10 === a && (a = 13);
  return 32 <= a || 13 === a ? a : 0;
}
function pd() {
  return true;
}
function qd() {
  return false;
}
function rd(a) {
  function b(b2, d, e, f2, g) {
    this._reactName = b2;
    this._targetInst = e;
    this.type = d;
    this.nativeEvent = f2;
    this.target = g;
    this.currentTarget = null;
    for (var c in a) a.hasOwnProperty(c) && (b2 = a[c], this[c] = b2 ? b2(f2) : f2[c]);
    this.isDefaultPrevented = (null != f2.defaultPrevented ? f2.defaultPrevented : false === f2.returnValue) ? pd : qd;
    this.isPropagationStopped = qd;
    return this;
  }
  A(b.prototype, { preventDefault: function() {
    this.defaultPrevented = true;
    var a2 = this.nativeEvent;
    a2 && (a2.preventDefault ? a2.preventDefault() : "unknown" !== typeof a2.returnValue && (a2.returnValue = false), this.isDefaultPrevented = pd);
  }, stopPropagation: function() {
    var a2 = this.nativeEvent;
    a2 && (a2.stopPropagation ? a2.stopPropagation() : "unknown" !== typeof a2.cancelBubble && (a2.cancelBubble = true), this.isPropagationStopped = pd);
  }, persist: function() {
  }, isPersistent: pd });
  return b;
}
var sd = { eventPhase: 0, bubbles: 0, cancelable: 0, timeStamp: function(a) {
  return a.timeStamp || Date.now();
}, defaultPrevented: 0, isTrusted: 0 }, td = rd(sd), ud = A({}, sd, { view: 0, detail: 0 }), vd = rd(ud), wd, xd, yd, Ad = A({}, ud, { screenX: 0, screenY: 0, clientX: 0, clientY: 0, pageX: 0, pageY: 0, ctrlKey: 0, shiftKey: 0, altKey: 0, metaKey: 0, getModifierState: zd, button: 0, buttons: 0, relatedTarget: function(a) {
  return void 0 === a.relatedTarget ? a.fromElement === a.srcElement ? a.toElement : a.fromElement : a.relatedTarget;
}, movementX: function(a) {
  if ("movementX" in a) return a.movementX;
  a !== yd && (yd && "mousemove" === a.type ? (wd = a.screenX - yd.screenX, xd = a.screenY - yd.screenY) : xd = wd = 0, yd = a);
  return wd;
}, movementY: function(a) {
  return "movementY" in a ? a.movementY : xd;
} }), Bd = rd(Ad), Cd = A({}, Ad, { dataTransfer: 0 }), Dd = rd(Cd), Ed = A({}, ud, { relatedTarget: 0 }), Fd = rd(Ed), Gd = A({}, sd, { animationName: 0, elapsedTime: 0, pseudoElement: 0 }), Hd = rd(Gd), Id = A({}, sd, { clipboardData: function(a) {
  return "clipboardData" in a ? a.clipboardData : window.clipboardData;
} }), Jd = rd(Id), Kd = A({}, sd, { data: 0 }), Ld = rd(Kd), Md = {
  Esc: "Escape",
  Spacebar: " ",
  Left: "ArrowLeft",
  Up: "ArrowUp",
  Right: "ArrowRight",
  Down: "ArrowDown",
  Del: "Delete",
  Win: "OS",
  Menu: "ContextMenu",
  Apps: "ContextMenu",
  Scroll: "ScrollLock",
  MozPrintableKey: "Unidentified"
}, Nd = {
  8: "Backspace",
  9: "Tab",
  12: "Clear",
  13: "Enter",
  16: "Shift",
  17: "Control",
  18: "Alt",
  19: "Pause",
  20: "CapsLock",
  27: "Escape",
  32: " ",
  33: "PageUp",
  34: "PageDown",
  35: "End",
  36: "Home",
  37: "ArrowLeft",
  38: "ArrowUp",
  39: "ArrowRight",
  40: "ArrowDown",
  45: "Insert",
  46: "Delete",
  112: "F1",
  113: "F2",
  114: "F3",
  115: "F4",
  116: "F5",
  117: "F6",
  118: "F7",
  119: "F8",
  120: "F9",
  121: "F10",
  122: "F11",
  123: "F12",
  144: "NumLock",
  145: "ScrollLock",
  224: "Meta"
}, Od = { Alt: "altKey", Control: "ctrlKey", Meta: "metaKey", Shift: "shiftKey" };
function Pd(a) {
  var b = this.nativeEvent;
  return b.getModifierState ? b.getModifierState(a) : (a = Od[a]) ? !!b[a] : false;
}
function zd() {
  return Pd;
}
var Qd = A({}, ud, { key: function(a) {
  if (a.key) {
    var b = Md[a.key] || a.key;
    if ("Unidentified" !== b) return b;
  }
  return "keypress" === a.type ? (a = od(a), 13 === a ? "Enter" : String.fromCharCode(a)) : "keydown" === a.type || "keyup" === a.type ? Nd[a.keyCode] || "Unidentified" : "";
}, code: 0, location: 0, ctrlKey: 0, shiftKey: 0, altKey: 0, metaKey: 0, repeat: 0, locale: 0, getModifierState: zd, charCode: function(a) {
  return "keypress" === a.type ? od(a) : 0;
}, keyCode: function(a) {
  return "keydown" === a.type || "keyup" === a.type ? a.keyCode : 0;
}, which: function(a) {
  return "keypress" === a.type ? od(a) : "keydown" === a.type || "keyup" === a.type ? a.keyCode : 0;
} }), Rd = rd(Qd), Sd = A({}, Ad, { pointerId: 0, width: 0, height: 0, pressure: 0, tangentialPressure: 0, tiltX: 0, tiltY: 0, twist: 0, pointerType: 0, isPrimary: 0 }), Td = rd(Sd), Ud = A({}, ud, { touches: 0, targetTouches: 0, changedTouches: 0, altKey: 0, metaKey: 0, ctrlKey: 0, shiftKey: 0, getModifierState: zd }), Vd = rd(Ud), Wd = A({}, sd, { propertyName: 0, elapsedTime: 0, pseudoElement: 0 }), Xd = rd(Wd), Yd = A({}, Ad, {
  deltaX: function(a) {
    return "deltaX" in a ? a.deltaX : "wheelDeltaX" in a ? -a.wheelDeltaX : 0;
  },
  deltaY: function(a) {
    return "deltaY" in a ? a.deltaY : "wheelDeltaY" in a ? -a.wheelDeltaY : "wheelDelta" in a ? -a.wheelDelta : 0;
  },
  deltaZ: 0,
  deltaMode: 0
}), Zd = rd(Yd), $d = [9, 13, 27, 32], ae$1 = ia && "CompositionEvent" in window, be$1 = null;
ia && "documentMode" in document && (be$1 = document.documentMode);
var ce = ia && "TextEvent" in window && !be$1, de$1 = ia && (!ae$1 || be$1 && 8 < be$1 && 11 >= be$1), ee$1 = String.fromCharCode(32), fe$1 = false;
function ge(a, b) {
  switch (a) {
    case "keyup":
      return -1 !== $d.indexOf(b.keyCode);
    case "keydown":
      return 229 !== b.keyCode;
    case "keypress":
    case "mousedown":
    case "focusout":
      return true;
    default:
      return false;
  }
}
function he$1(a) {
  a = a.detail;
  return "object" === typeof a && "data" in a ? a.data : null;
}
var ie$1 = false;
function je(a, b) {
  switch (a) {
    case "compositionend":
      return he$1(b);
    case "keypress":
      if (32 !== b.which) return null;
      fe$1 = true;
      return ee$1;
    case "textInput":
      return a = b.data, a === ee$1 && fe$1 ? null : a;
    default:
      return null;
  }
}
function ke(a, b) {
  if (ie$1) return "compositionend" === a || !ae$1 && ge(a, b) ? (a = nd(), md = ld = kd = null, ie$1 = false, a) : null;
  switch (a) {
    case "paste":
      return null;
    case "keypress":
      if (!(b.ctrlKey || b.altKey || b.metaKey) || b.ctrlKey && b.altKey) {
        if (b.char && 1 < b.char.length) return b.char;
        if (b.which) return String.fromCharCode(b.which);
      }
      return null;
    case "compositionend":
      return de$1 && "ko" !== b.locale ? null : b.data;
    default:
      return null;
  }
}
var le$1 = { color: true, date: true, datetime: true, "datetime-local": true, email: true, month: true, number: true, password: true, range: true, search: true, tel: true, text: true, time: true, url: true, week: true };
function me(a) {
  var b = a && a.nodeName && a.nodeName.toLowerCase();
  return "input" === b ? !!le$1[a.type] : "textarea" === b ? true : false;
}
function ne(a, b, c, d) {
  Eb(d);
  b = oe(b, "onChange");
  0 < b.length && (c = new td("onChange", "change", null, c, d), a.push({ event: c, listeners: b }));
}
var pe = null, qe = null;
function re(a) {
  se$1(a, 0);
}
function te$1(a) {
  var b = ue(a);
  if (Wa(b)) return a;
}
function ve(a, b) {
  if ("change" === a) return b;
}
var we$1 = false;
if (ia) {
  var xe;
  if (ia) {
    var ye = "oninput" in document;
    if (!ye) {
      var ze = document.createElement("div");
      ze.setAttribute("oninput", "return;");
      ye = "function" === typeof ze.oninput;
    }
    xe = ye;
  } else xe = false;
  we$1 = xe && (!document.documentMode || 9 < document.documentMode);
}
function Ae() {
  pe && (pe.detachEvent("onpropertychange", Be), qe = pe = null);
}
function Be(a) {
  if ("value" === a.propertyName && te$1(qe)) {
    var b = [];
    ne(b, qe, a, xb(a));
    Jb(re, b);
  }
}
function Ce$1(a, b, c) {
  "focusin" === a ? (Ae(), pe = b, qe = c, pe.attachEvent("onpropertychange", Be)) : "focusout" === a && Ae();
}
function De$1(a) {
  if ("selectionchange" === a || "keyup" === a || "keydown" === a) return te$1(qe);
}
function Ee$1(a, b) {
  if ("click" === a) return te$1(b);
}
function Fe(a, b) {
  if ("input" === a || "change" === a) return te$1(b);
}
function Ge(a, b) {
  return a === b && (0 !== a || 1 / a === 1 / b) || a !== a && b !== b;
}
var He$1 = "function" === typeof Object.is ? Object.is : Ge;
function Ie(a, b) {
  if (He$1(a, b)) return true;
  if ("object" !== typeof a || null === a || "object" !== typeof b || null === b) return false;
  var c = Object.keys(a), d = Object.keys(b);
  if (c.length !== d.length) return false;
  for (d = 0; d < c.length; d++) {
    var e = c[d];
    if (!ja.call(b, e) || !He$1(a[e], b[e])) return false;
  }
  return true;
}
function Je(a) {
  for (; a && a.firstChild; ) a = a.firstChild;
  return a;
}
function Ke(a, b) {
  var c = Je(a);
  a = 0;
  for (var d; c; ) {
    if (3 === c.nodeType) {
      d = a + c.textContent.length;
      if (a <= b && d >= b) return { node: c, offset: b - a };
      a = d;
    }
    a: {
      for (; c; ) {
        if (c.nextSibling) {
          c = c.nextSibling;
          break a;
        }
        c = c.parentNode;
      }
      c = void 0;
    }
    c = Je(c);
  }
}
function Le(a, b) {
  return a && b ? a === b ? true : a && 3 === a.nodeType ? false : b && 3 === b.nodeType ? Le(a, b.parentNode) : "contains" in a ? a.contains(b) : a.compareDocumentPosition ? !!(a.compareDocumentPosition(b) & 16) : false : false;
}
function Me$1() {
  for (var a = window, b = Xa(); b instanceof a.HTMLIFrameElement; ) {
    try {
      var c = "string" === typeof b.contentWindow.location.href;
    } catch (d) {
      c = false;
    }
    if (c) a = b.contentWindow;
    else break;
    b = Xa(a.document);
  }
  return b;
}
function Ne(a) {
  var b = a && a.nodeName && a.nodeName.toLowerCase();
  return b && ("input" === b && ("text" === a.type || "search" === a.type || "tel" === a.type || "url" === a.type || "password" === a.type) || "textarea" === b || "true" === a.contentEditable);
}
function Oe$1(a) {
  var b = Me$1(), c = a.focusedElem, d = a.selectionRange;
  if (b !== c && c && c.ownerDocument && Le(c.ownerDocument.documentElement, c)) {
    if (null !== d && Ne(c)) {
      if (b = d.start, a = d.end, void 0 === a && (a = b), "selectionStart" in c) c.selectionStart = b, c.selectionEnd = Math.min(a, c.value.length);
      else if (a = (b = c.ownerDocument || document) && b.defaultView || window, a.getSelection) {
        a = a.getSelection();
        var e = c.textContent.length, f2 = Math.min(d.start, e);
        d = void 0 === d.end ? f2 : Math.min(d.end, e);
        !a.extend && f2 > d && (e = d, d = f2, f2 = e);
        e = Ke(c, f2);
        var g = Ke(
          c,
          d
        );
        e && g && (1 !== a.rangeCount || a.anchorNode !== e.node || a.anchorOffset !== e.offset || a.focusNode !== g.node || a.focusOffset !== g.offset) && (b = b.createRange(), b.setStart(e.node, e.offset), a.removeAllRanges(), f2 > d ? (a.addRange(b), a.extend(g.node, g.offset)) : (b.setEnd(g.node, g.offset), a.addRange(b)));
      }
    }
    b = [];
    for (a = c; a = a.parentNode; ) 1 === a.nodeType && b.push({ element: a, left: a.scrollLeft, top: a.scrollTop });
    "function" === typeof c.focus && c.focus();
    for (c = 0; c < b.length; c++) a = b[c], a.element.scrollLeft = a.left, a.element.scrollTop = a.top;
  }
}
var Pe = ia && "documentMode" in document && 11 >= document.documentMode, Qe = null, Re = null, Se = null, Te = false;
function Ue(a, b, c) {
  var d = c.window === c ? c.document : 9 === c.nodeType ? c : c.ownerDocument;
  Te || null == Qe || Qe !== Xa(d) || (d = Qe, "selectionStart" in d && Ne(d) ? d = { start: d.selectionStart, end: d.selectionEnd } : (d = (d.ownerDocument && d.ownerDocument.defaultView || window).getSelection(), d = { anchorNode: d.anchorNode, anchorOffset: d.anchorOffset, focusNode: d.focusNode, focusOffset: d.focusOffset }), Se && Ie(Se, d) || (Se = d, d = oe(Re, "onSelect"), 0 < d.length && (b = new td("onSelect", "select", null, b, c), a.push({ event: b, listeners: d }), b.target = Qe)));
}
function Ve$1(a, b) {
  var c = {};
  c[a.toLowerCase()] = b.toLowerCase();
  c["Webkit" + a] = "webkit" + b;
  c["Moz" + a] = "moz" + b;
  return c;
}
var We = { animationend: Ve$1("Animation", "AnimationEnd"), animationiteration: Ve$1("Animation", "AnimationIteration"), animationstart: Ve$1("Animation", "AnimationStart"), transitionend: Ve$1("Transition", "TransitionEnd") }, Xe = {}, Ye = {};
ia && (Ye = document.createElement("div").style, "AnimationEvent" in window || (delete We.animationend.animation, delete We.animationiteration.animation, delete We.animationstart.animation), "TransitionEvent" in window || delete We.transitionend.transition);
function Ze(a) {
  if (Xe[a]) return Xe[a];
  if (!We[a]) return a;
  var b = We[a], c;
  for (c in b) if (b.hasOwnProperty(c) && c in Ye) return Xe[a] = b[c];
  return a;
}
var $e = Ze("animationend"), af = Ze("animationiteration"), bf = Ze("animationstart"), cf = Ze("transitionend"), df = /* @__PURE__ */ new Map(), ef = "abort auxClick cancel canPlay canPlayThrough click close contextMenu copy cut drag dragEnd dragEnter dragExit dragLeave dragOver dragStart drop durationChange emptied encrypted ended error gotPointerCapture input invalid keyDown keyPress keyUp load loadedData loadedMetadata loadStart lostPointerCapture mouseDown mouseMove mouseOut mouseOver mouseUp paste pause play playing pointerCancel pointerDown pointerMove pointerOut pointerOver pointerUp progress rateChange reset resize seeked seeking stalled submit suspend timeUpdate touchCancel touchEnd touchStart volumeChange scroll toggle touchMove waiting wheel".split(" ");
function ff(a, b) {
  df.set(a, b);
  fa(b, [a]);
}
for (var gf = 0; gf < ef.length; gf++) {
  var hf = ef[gf], jf = hf.toLowerCase(), kf = hf[0].toUpperCase() + hf.slice(1);
  ff(jf, "on" + kf);
}
ff($e, "onAnimationEnd");
ff(af, "onAnimationIteration");
ff(bf, "onAnimationStart");
ff("dblclick", "onDoubleClick");
ff("focusin", "onFocus");
ff("focusout", "onBlur");
ff(cf, "onTransitionEnd");
ha("onMouseEnter", ["mouseout", "mouseover"]);
ha("onMouseLeave", ["mouseout", "mouseover"]);
ha("onPointerEnter", ["pointerout", "pointerover"]);
ha("onPointerLeave", ["pointerout", "pointerover"]);
fa("onChange", "change click focusin focusout input keydown keyup selectionchange".split(" "));
fa("onSelect", "focusout contextmenu dragend focusin keydown keyup mousedown mouseup selectionchange".split(" "));
fa("onBeforeInput", ["compositionend", "keypress", "textInput", "paste"]);
fa("onCompositionEnd", "compositionend focusout keydown keypress keyup mousedown".split(" "));
fa("onCompositionStart", "compositionstart focusout keydown keypress keyup mousedown".split(" "));
fa("onCompositionUpdate", "compositionupdate focusout keydown keypress keyup mousedown".split(" "));
var lf = "abort canplay canplaythrough durationchange emptied encrypted ended error loadeddata loadedmetadata loadstart pause play playing progress ratechange resize seeked seeking stalled suspend timeupdate volumechange waiting".split(" "), mf = new Set("cancel close invalid load scroll toggle".split(" ").concat(lf));
function nf(a, b, c) {
  var d = a.type || "unknown-event";
  a.currentTarget = c;
  Ub(d, b, void 0, a);
  a.currentTarget = null;
}
function se$1(a, b) {
  b = 0 !== (b & 4);
  for (var c = 0; c < a.length; c++) {
    var d = a[c], e = d.event;
    d = d.listeners;
    a: {
      var f2 = void 0;
      if (b) for (var g = d.length - 1; 0 <= g; g--) {
        var h2 = d[g], k2 = h2.instance, l2 = h2.currentTarget;
        h2 = h2.listener;
        if (k2 !== f2 && e.isPropagationStopped()) break a;
        nf(e, h2, l2);
        f2 = k2;
      }
      else for (g = 0; g < d.length; g++) {
        h2 = d[g];
        k2 = h2.instance;
        l2 = h2.currentTarget;
        h2 = h2.listener;
        if (k2 !== f2 && e.isPropagationStopped()) break a;
        nf(e, h2, l2);
        f2 = k2;
      }
    }
  }
  if (Qb) throw a = Rb, Qb = false, Rb = null, a;
}
function D$1(a, b) {
  var c = b[of];
  void 0 === c && (c = b[of] = /* @__PURE__ */ new Set());
  var d = a + "__bubble";
  c.has(d) || (pf(b, a, 2, false), c.add(d));
}
function qf(a, b, c) {
  var d = 0;
  b && (d |= 4);
  pf(c, a, d, b);
}
var rf = "_reactListening" + Math.random().toString(36).slice(2);
function sf(a) {
  if (!a[rf]) {
    a[rf] = true;
    da.forEach(function(b2) {
      "selectionchange" !== b2 && (mf.has(b2) || qf(b2, false, a), qf(b2, true, a));
    });
    var b = 9 === a.nodeType ? a : a.ownerDocument;
    null === b || b[rf] || (b[rf] = true, qf("selectionchange", false, b));
  }
}
function pf(a, b, c, d) {
  switch (jd(b)) {
    case 1:
      var e = ed;
      break;
    case 4:
      e = gd;
      break;
    default:
      e = fd;
  }
  c = e.bind(null, b, c, a);
  e = void 0;
  !Lb || "touchstart" !== b && "touchmove" !== b && "wheel" !== b || (e = true);
  d ? void 0 !== e ? a.addEventListener(b, c, { capture: true, passive: e }) : a.addEventListener(b, c, true) : void 0 !== e ? a.addEventListener(b, c, { passive: e }) : a.addEventListener(b, c, false);
}
function hd(a, b, c, d, e) {
  var f2 = d;
  if (0 === (b & 1) && 0 === (b & 2) && null !== d) a: for (; ; ) {
    if (null === d) return;
    var g = d.tag;
    if (3 === g || 4 === g) {
      var h2 = d.stateNode.containerInfo;
      if (h2 === e || 8 === h2.nodeType && h2.parentNode === e) break;
      if (4 === g) for (g = d.return; null !== g; ) {
        var k2 = g.tag;
        if (3 === k2 || 4 === k2) {
          if (k2 = g.stateNode.containerInfo, k2 === e || 8 === k2.nodeType && k2.parentNode === e) return;
        }
        g = g.return;
      }
      for (; null !== h2; ) {
        g = Wc(h2);
        if (null === g) return;
        k2 = g.tag;
        if (5 === k2 || 6 === k2) {
          d = f2 = g;
          continue a;
        }
        h2 = h2.parentNode;
      }
    }
    d = d.return;
  }
  Jb(function() {
    var d2 = f2, e2 = xb(c), g2 = [];
    a: {
      var h3 = df.get(a);
      if (void 0 !== h3) {
        var k3 = td, n2 = a;
        switch (a) {
          case "keypress":
            if (0 === od(c)) break a;
          case "keydown":
          case "keyup":
            k3 = Rd;
            break;
          case "focusin":
            n2 = "focus";
            k3 = Fd;
            break;
          case "focusout":
            n2 = "blur";
            k3 = Fd;
            break;
          case "beforeblur":
          case "afterblur":
            k3 = Fd;
            break;
          case "click":
            if (2 === c.button) break a;
          case "auxclick":
          case "dblclick":
          case "mousedown":
          case "mousemove":
          case "mouseup":
          case "mouseout":
          case "mouseover":
          case "contextmenu":
            k3 = Bd;
            break;
          case "drag":
          case "dragend":
          case "dragenter":
          case "dragexit":
          case "dragleave":
          case "dragover":
          case "dragstart":
          case "drop":
            k3 = Dd;
            break;
          case "touchcancel":
          case "touchend":
          case "touchmove":
          case "touchstart":
            k3 = Vd;
            break;
          case $e:
          case af:
          case bf:
            k3 = Hd;
            break;
          case cf:
            k3 = Xd;
            break;
          case "scroll":
            k3 = vd;
            break;
          case "wheel":
            k3 = Zd;
            break;
          case "copy":
          case "cut":
          case "paste":
            k3 = Jd;
            break;
          case "gotpointercapture":
          case "lostpointercapture":
          case "pointercancel":
          case "pointerdown":
          case "pointermove":
          case "pointerout":
          case "pointerover":
          case "pointerup":
            k3 = Td;
        }
        var t2 = 0 !== (b & 4), J2 = !t2 && "scroll" === a, x2 = t2 ? null !== h3 ? h3 + "Capture" : null : h3;
        t2 = [];
        for (var w2 = d2, u2; null !== w2; ) {
          u2 = w2;
          var F2 = u2.stateNode;
          5 === u2.tag && null !== F2 && (u2 = F2, null !== x2 && (F2 = Kb(w2, x2), null != F2 && t2.push(tf(w2, F2, u2))));
          if (J2) break;
          w2 = w2.return;
        }
        0 < t2.length && (h3 = new k3(h3, n2, null, c, e2), g2.push({ event: h3, listeners: t2 }));
      }
    }
    if (0 === (b & 7)) {
      a: {
        h3 = "mouseover" === a || "pointerover" === a;
        k3 = "mouseout" === a || "pointerout" === a;
        if (h3 && c !== wb && (n2 = c.relatedTarget || c.fromElement) && (Wc(n2) || n2[uf])) break a;
        if (k3 || h3) {
          h3 = e2.window === e2 ? e2 : (h3 = e2.ownerDocument) ? h3.defaultView || h3.parentWindow : window;
          if (k3) {
            if (n2 = c.relatedTarget || c.toElement, k3 = d2, n2 = n2 ? Wc(n2) : null, null !== n2 && (J2 = Vb(n2), n2 !== J2 || 5 !== n2.tag && 6 !== n2.tag)) n2 = null;
          } else k3 = null, n2 = d2;
          if (k3 !== n2) {
            t2 = Bd;
            F2 = "onMouseLeave";
            x2 = "onMouseEnter";
            w2 = "mouse";
            if ("pointerout" === a || "pointerover" === a) t2 = Td, F2 = "onPointerLeave", x2 = "onPointerEnter", w2 = "pointer";
            J2 = null == k3 ? h3 : ue(k3);
            u2 = null == n2 ? h3 : ue(n2);
            h3 = new t2(F2, w2 + "leave", k3, c, e2);
            h3.target = J2;
            h3.relatedTarget = u2;
            F2 = null;
            Wc(e2) === d2 && (t2 = new t2(x2, w2 + "enter", n2, c, e2), t2.target = u2, t2.relatedTarget = J2, F2 = t2);
            J2 = F2;
            if (k3 && n2) b: {
              t2 = k3;
              x2 = n2;
              w2 = 0;
              for (u2 = t2; u2; u2 = vf(u2)) w2++;
              u2 = 0;
              for (F2 = x2; F2; F2 = vf(F2)) u2++;
              for (; 0 < w2 - u2; ) t2 = vf(t2), w2--;
              for (; 0 < u2 - w2; ) x2 = vf(x2), u2--;
              for (; w2--; ) {
                if (t2 === x2 || null !== x2 && t2 === x2.alternate) break b;
                t2 = vf(t2);
                x2 = vf(x2);
              }
              t2 = null;
            }
            else t2 = null;
            null !== k3 && wf(g2, h3, k3, t2, false);
            null !== n2 && null !== J2 && wf(g2, J2, n2, t2, true);
          }
        }
      }
      a: {
        h3 = d2 ? ue(d2) : window;
        k3 = h3.nodeName && h3.nodeName.toLowerCase();
        if ("select" === k3 || "input" === k3 && "file" === h3.type) var na = ve;
        else if (me(h3)) if (we$1) na = Fe;
        else {
          na = De$1;
          var xa = Ce$1;
        }
        else (k3 = h3.nodeName) && "input" === k3.toLowerCase() && ("checkbox" === h3.type || "radio" === h3.type) && (na = Ee$1);
        if (na && (na = na(a, d2))) {
          ne(g2, na, c, e2);
          break a;
        }
        xa && xa(a, h3, d2);
        "focusout" === a && (xa = h3._wrapperState) && xa.controlled && "number" === h3.type && cb(h3, "number", h3.value);
      }
      xa = d2 ? ue(d2) : window;
      switch (a) {
        case "focusin":
          if (me(xa) || "true" === xa.contentEditable) Qe = xa, Re = d2, Se = null;
          break;
        case "focusout":
          Se = Re = Qe = null;
          break;
        case "mousedown":
          Te = true;
          break;
        case "contextmenu":
        case "mouseup":
        case "dragend":
          Te = false;
          Ue(g2, c, e2);
          break;
        case "selectionchange":
          if (Pe) break;
        case "keydown":
        case "keyup":
          Ue(g2, c, e2);
      }
      var $a;
      if (ae$1) b: {
        switch (a) {
          case "compositionstart":
            var ba = "onCompositionStart";
            break b;
          case "compositionend":
            ba = "onCompositionEnd";
            break b;
          case "compositionupdate":
            ba = "onCompositionUpdate";
            break b;
        }
        ba = void 0;
      }
      else ie$1 ? ge(a, c) && (ba = "onCompositionEnd") : "keydown" === a && 229 === c.keyCode && (ba = "onCompositionStart");
      ba && (de$1 && "ko" !== c.locale && (ie$1 || "onCompositionStart" !== ba ? "onCompositionEnd" === ba && ie$1 && ($a = nd()) : (kd = e2, ld = "value" in kd ? kd.value : kd.textContent, ie$1 = true)), xa = oe(d2, ba), 0 < xa.length && (ba = new Ld(ba, a, null, c, e2), g2.push({ event: ba, listeners: xa }), $a ? ba.data = $a : ($a = he$1(c), null !== $a && (ba.data = $a))));
      if ($a = ce ? je(a, c) : ke(a, c)) d2 = oe(d2, "onBeforeInput"), 0 < d2.length && (e2 = new Ld("onBeforeInput", "beforeinput", null, c, e2), g2.push({ event: e2, listeners: d2 }), e2.data = $a);
    }
    se$1(g2, b);
  });
}
function tf(a, b, c) {
  return { instance: a, listener: b, currentTarget: c };
}
function oe(a, b) {
  for (var c = b + "Capture", d = []; null !== a; ) {
    var e = a, f2 = e.stateNode;
    5 === e.tag && null !== f2 && (e = f2, f2 = Kb(a, c), null != f2 && d.unshift(tf(a, f2, e)), f2 = Kb(a, b), null != f2 && d.push(tf(a, f2, e)));
    a = a.return;
  }
  return d;
}
function vf(a) {
  if (null === a) return null;
  do
    a = a.return;
  while (a && 5 !== a.tag);
  return a ? a : null;
}
function wf(a, b, c, d, e) {
  for (var f2 = b._reactName, g = []; null !== c && c !== d; ) {
    var h2 = c, k2 = h2.alternate, l2 = h2.stateNode;
    if (null !== k2 && k2 === d) break;
    5 === h2.tag && null !== l2 && (h2 = l2, e ? (k2 = Kb(c, f2), null != k2 && g.unshift(tf(c, k2, h2))) : e || (k2 = Kb(c, f2), null != k2 && g.push(tf(c, k2, h2))));
    c = c.return;
  }
  0 !== g.length && a.push({ event: b, listeners: g });
}
var xf = /\r\n?/g, yf = /\u0000|\uFFFD/g;
function zf(a) {
  return ("string" === typeof a ? a : "" + a).replace(xf, "\n").replace(yf, "");
}
function Af(a, b, c) {
  b = zf(b);
  if (zf(a) !== b && c) throw Error(p(425));
}
function Bf() {
}
var Cf = null, Df = null;
function Ef(a, b) {
  return "textarea" === a || "noscript" === a || "string" === typeof b.children || "number" === typeof b.children || "object" === typeof b.dangerouslySetInnerHTML && null !== b.dangerouslySetInnerHTML && null != b.dangerouslySetInnerHTML.__html;
}
var Ff = "function" === typeof setTimeout ? setTimeout : void 0, Gf = "function" === typeof clearTimeout ? clearTimeout : void 0, Hf = "function" === typeof Promise ? Promise : void 0, Jf = "function" === typeof queueMicrotask ? queueMicrotask : "undefined" !== typeof Hf ? function(a) {
  return Hf.resolve(null).then(a).catch(If);
} : Ff;
function If(a) {
  setTimeout(function() {
    throw a;
  });
}
function Kf(a, b) {
  var c = b, d = 0;
  do {
    var e = c.nextSibling;
    a.removeChild(c);
    if (e && 8 === e.nodeType) if (c = e.data, "/$" === c) {
      if (0 === d) {
        a.removeChild(e);
        bd(b);
        return;
      }
      d--;
    } else "$" !== c && "$?" !== c && "$!" !== c || d++;
    c = e;
  } while (c);
  bd(b);
}
function Lf(a) {
  for (; null != a; a = a.nextSibling) {
    var b = a.nodeType;
    if (1 === b || 3 === b) break;
    if (8 === b) {
      b = a.data;
      if ("$" === b || "$!" === b || "$?" === b) break;
      if ("/$" === b) return null;
    }
  }
  return a;
}
function Mf(a) {
  a = a.previousSibling;
  for (var b = 0; a; ) {
    if (8 === a.nodeType) {
      var c = a.data;
      if ("$" === c || "$!" === c || "$?" === c) {
        if (0 === b) return a;
        b--;
      } else "/$" === c && b++;
    }
    a = a.previousSibling;
  }
  return null;
}
var Nf = Math.random().toString(36).slice(2), Of = "__reactFiber$" + Nf, Pf = "__reactProps$" + Nf, uf = "__reactContainer$" + Nf, of = "__reactEvents$" + Nf, Qf = "__reactListeners$" + Nf, Rf = "__reactHandles$" + Nf;
function Wc(a) {
  var b = a[Of];
  if (b) return b;
  for (var c = a.parentNode; c; ) {
    if (b = c[uf] || c[Of]) {
      c = b.alternate;
      if (null !== b.child || null !== c && null !== c.child) for (a = Mf(a); null !== a; ) {
        if (c = a[Of]) return c;
        a = Mf(a);
      }
      return b;
    }
    a = c;
    c = a.parentNode;
  }
  return null;
}
function Cb(a) {
  a = a[Of] || a[uf];
  return !a || 5 !== a.tag && 6 !== a.tag && 13 !== a.tag && 3 !== a.tag ? null : a;
}
function ue(a) {
  if (5 === a.tag || 6 === a.tag) return a.stateNode;
  throw Error(p(33));
}
function Db(a) {
  return a[Pf] || null;
}
var Sf = [], Tf = -1;
function Uf(a) {
  return { current: a };
}
function E(a) {
  0 > Tf || (a.current = Sf[Tf], Sf[Tf] = null, Tf--);
}
function G(a, b) {
  Tf++;
  Sf[Tf] = a.current;
  a.current = b;
}
var Vf = {}, H$1 = Uf(Vf), Wf = Uf(false), Xf = Vf;
function Yf(a, b) {
  var c = a.type.contextTypes;
  if (!c) return Vf;
  var d = a.stateNode;
  if (d && d.__reactInternalMemoizedUnmaskedChildContext === b) return d.__reactInternalMemoizedMaskedChildContext;
  var e = {}, f2;
  for (f2 in c) e[f2] = b[f2];
  d && (a = a.stateNode, a.__reactInternalMemoizedUnmaskedChildContext = b, a.__reactInternalMemoizedMaskedChildContext = e);
  return e;
}
function Zf(a) {
  a = a.childContextTypes;
  return null !== a && void 0 !== a;
}
function $f() {
  E(Wf);
  E(H$1);
}
function ag(a, b, c) {
  if (H$1.current !== Vf) throw Error(p(168));
  G(H$1, b);
  G(Wf, c);
}
function bg(a, b, c) {
  var d = a.stateNode;
  b = b.childContextTypes;
  if ("function" !== typeof d.getChildContext) return c;
  d = d.getChildContext();
  for (var e in d) if (!(e in b)) throw Error(p(108, Ra(a) || "Unknown", e));
  return A({}, c, d);
}
function cg(a) {
  a = (a = a.stateNode) && a.__reactInternalMemoizedMergedChildContext || Vf;
  Xf = H$1.current;
  G(H$1, a);
  G(Wf, Wf.current);
  return true;
}
function dg(a, b, c) {
  var d = a.stateNode;
  if (!d) throw Error(p(169));
  c ? (a = bg(a, b, Xf), d.__reactInternalMemoizedMergedChildContext = a, E(Wf), E(H$1), G(H$1, a)) : E(Wf);
  G(Wf, c);
}
var eg = null, fg = false, gg = false;
function hg(a) {
  null === eg ? eg = [a] : eg.push(a);
}
function ig(a) {
  fg = true;
  hg(a);
}
function jg() {
  if (!gg && null !== eg) {
    gg = true;
    var a = 0, b = C;
    try {
      var c = eg;
      for (C = 1; a < c.length; a++) {
        var d = c[a];
        do
          d = d(true);
        while (null !== d);
      }
      eg = null;
      fg = false;
    } catch (e) {
      throw null !== eg && (eg = eg.slice(a + 1)), ac(fc, jg), e;
    } finally {
      C = b, gg = false;
    }
  }
  return null;
}
var kg = [], lg = 0, mg = null, ng = 0, og = [], pg = 0, qg = null, rg = 1, sg = "";
function tg(a, b) {
  kg[lg++] = ng;
  kg[lg++] = mg;
  mg = a;
  ng = b;
}
function ug(a, b, c) {
  og[pg++] = rg;
  og[pg++] = sg;
  og[pg++] = qg;
  qg = a;
  var d = rg;
  a = sg;
  var e = 32 - oc(d) - 1;
  d &= ~(1 << e);
  c += 1;
  var f2 = 32 - oc(b) + e;
  if (30 < f2) {
    var g = e - e % 5;
    f2 = (d & (1 << g) - 1).toString(32);
    d >>= g;
    e -= g;
    rg = 1 << 32 - oc(b) + e | c << e | d;
    sg = f2 + a;
  } else rg = 1 << f2 | c << e | d, sg = a;
}
function vg(a) {
  null !== a.return && (tg(a, 1), ug(a, 1, 0));
}
function wg(a) {
  for (; a === mg; ) mg = kg[--lg], kg[lg] = null, ng = kg[--lg], kg[lg] = null;
  for (; a === qg; ) qg = og[--pg], og[pg] = null, sg = og[--pg], og[pg] = null, rg = og[--pg], og[pg] = null;
}
var xg = null, yg = null, I = false, zg = null;
function Ag(a, b) {
  var c = Bg(5, null, null, 0);
  c.elementType = "DELETED";
  c.stateNode = b;
  c.return = a;
  b = a.deletions;
  null === b ? (a.deletions = [c], a.flags |= 16) : b.push(c);
}
function Cg(a, b) {
  switch (a.tag) {
    case 5:
      var c = a.type;
      b = 1 !== b.nodeType || c.toLowerCase() !== b.nodeName.toLowerCase() ? null : b;
      return null !== b ? (a.stateNode = b, xg = a, yg = Lf(b.firstChild), true) : false;
    case 6:
      return b = "" === a.pendingProps || 3 !== b.nodeType ? null : b, null !== b ? (a.stateNode = b, xg = a, yg = null, true) : false;
    case 13:
      return b = 8 !== b.nodeType ? null : b, null !== b ? (c = null !== qg ? { id: rg, overflow: sg } : null, a.memoizedState = { dehydrated: b, treeContext: c, retryLane: 1073741824 }, c = Bg(18, null, null, 0), c.stateNode = b, c.return = a, a.child = c, xg = a, yg = null, true) : false;
    default:
      return false;
  }
}
function Dg(a) {
  return 0 !== (a.mode & 1) && 0 === (a.flags & 128);
}
function Eg(a) {
  if (I) {
    var b = yg;
    if (b) {
      var c = b;
      if (!Cg(a, b)) {
        if (Dg(a)) throw Error(p(418));
        b = Lf(c.nextSibling);
        var d = xg;
        b && Cg(a, b) ? Ag(d, c) : (a.flags = a.flags & -4097 | 2, I = false, xg = a);
      }
    } else {
      if (Dg(a)) throw Error(p(418));
      a.flags = a.flags & -4097 | 2;
      I = false;
      xg = a;
    }
  }
}
function Fg(a) {
  for (a = a.return; null !== a && 5 !== a.tag && 3 !== a.tag && 13 !== a.tag; ) a = a.return;
  xg = a;
}
function Gg(a) {
  if (a !== xg) return false;
  if (!I) return Fg(a), I = true, false;
  var b;
  (b = 3 !== a.tag) && !(b = 5 !== a.tag) && (b = a.type, b = "head" !== b && "body" !== b && !Ef(a.type, a.memoizedProps));
  if (b && (b = yg)) {
    if (Dg(a)) throw Hg(), Error(p(418));
    for (; b; ) Ag(a, b), b = Lf(b.nextSibling);
  }
  Fg(a);
  if (13 === a.tag) {
    a = a.memoizedState;
    a = null !== a ? a.dehydrated : null;
    if (!a) throw Error(p(317));
    a: {
      a = a.nextSibling;
      for (b = 0; a; ) {
        if (8 === a.nodeType) {
          var c = a.data;
          if ("/$" === c) {
            if (0 === b) {
              yg = Lf(a.nextSibling);
              break a;
            }
            b--;
          } else "$" !== c && "$!" !== c && "$?" !== c || b++;
        }
        a = a.nextSibling;
      }
      yg = null;
    }
  } else yg = xg ? Lf(a.stateNode.nextSibling) : null;
  return true;
}
function Hg() {
  for (var a = yg; a; ) a = Lf(a.nextSibling);
}
function Ig() {
  yg = xg = null;
  I = false;
}
function Jg(a) {
  null === zg ? zg = [a] : zg.push(a);
}
var Kg = ua.ReactCurrentBatchConfig;
function Lg(a, b, c) {
  a = c.ref;
  if (null !== a && "function" !== typeof a && "object" !== typeof a) {
    if (c._owner) {
      c = c._owner;
      if (c) {
        if (1 !== c.tag) throw Error(p(309));
        var d = c.stateNode;
      }
      if (!d) throw Error(p(147, a));
      var e = d, f2 = "" + a;
      if (null !== b && null !== b.ref && "function" === typeof b.ref && b.ref._stringRef === f2) return b.ref;
      b = function(a2) {
        var b2 = e.refs;
        null === a2 ? delete b2[f2] : b2[f2] = a2;
      };
      b._stringRef = f2;
      return b;
    }
    if ("string" !== typeof a) throw Error(p(284));
    if (!c._owner) throw Error(p(290, a));
  }
  return a;
}
function Mg(a, b) {
  a = Object.prototype.toString.call(b);
  throw Error(p(31, "[object Object]" === a ? "object with keys {" + Object.keys(b).join(", ") + "}" : a));
}
function Ng(a) {
  var b = a._init;
  return b(a._payload);
}
function Og(a) {
  function b(b2, c2) {
    if (a) {
      var d2 = b2.deletions;
      null === d2 ? (b2.deletions = [c2], b2.flags |= 16) : d2.push(c2);
    }
  }
  function c(c2, d2) {
    if (!a) return null;
    for (; null !== d2; ) b(c2, d2), d2 = d2.sibling;
    return null;
  }
  function d(a2, b2) {
    for (a2 = /* @__PURE__ */ new Map(); null !== b2; ) null !== b2.key ? a2.set(b2.key, b2) : a2.set(b2.index, b2), b2 = b2.sibling;
    return a2;
  }
  function e(a2, b2) {
    a2 = Pg(a2, b2);
    a2.index = 0;
    a2.sibling = null;
    return a2;
  }
  function f2(b2, c2, d2) {
    b2.index = d2;
    if (!a) return b2.flags |= 1048576, c2;
    d2 = b2.alternate;
    if (null !== d2) return d2 = d2.index, d2 < c2 ? (b2.flags |= 2, c2) : d2;
    b2.flags |= 2;
    return c2;
  }
  function g(b2) {
    a && null === b2.alternate && (b2.flags |= 2);
    return b2;
  }
  function h2(a2, b2, c2, d2) {
    if (null === b2 || 6 !== b2.tag) return b2 = Qg(c2, a2.mode, d2), b2.return = a2, b2;
    b2 = e(b2, c2);
    b2.return = a2;
    return b2;
  }
  function k2(a2, b2, c2, d2) {
    var f3 = c2.type;
    if (f3 === ya) return m2(a2, b2, c2.props.children, d2, c2.key);
    if (null !== b2 && (b2.elementType === f3 || "object" === typeof f3 && null !== f3 && f3.$$typeof === Ha && Ng(f3) === b2.type)) return d2 = e(b2, c2.props), d2.ref = Lg(a2, b2, c2), d2.return = a2, d2;
    d2 = Rg(c2.type, c2.key, c2.props, null, a2.mode, d2);
    d2.ref = Lg(a2, b2, c2);
    d2.return = a2;
    return d2;
  }
  function l2(a2, b2, c2, d2) {
    if (null === b2 || 4 !== b2.tag || b2.stateNode.containerInfo !== c2.containerInfo || b2.stateNode.implementation !== c2.implementation) return b2 = Sg(c2, a2.mode, d2), b2.return = a2, b2;
    b2 = e(b2, c2.children || []);
    b2.return = a2;
    return b2;
  }
  function m2(a2, b2, c2, d2, f3) {
    if (null === b2 || 7 !== b2.tag) return b2 = Tg(c2, a2.mode, d2, f3), b2.return = a2, b2;
    b2 = e(b2, c2);
    b2.return = a2;
    return b2;
  }
  function q2(a2, b2, c2) {
    if ("string" === typeof b2 && "" !== b2 || "number" === typeof b2) return b2 = Qg("" + b2, a2.mode, c2), b2.return = a2, b2;
    if ("object" === typeof b2 && null !== b2) {
      switch (b2.$$typeof) {
        case va:
          return c2 = Rg(b2.type, b2.key, b2.props, null, a2.mode, c2), c2.ref = Lg(a2, null, b2), c2.return = a2, c2;
        case wa:
          return b2 = Sg(b2, a2.mode, c2), b2.return = a2, b2;
        case Ha:
          var d2 = b2._init;
          return q2(a2, d2(b2._payload), c2);
      }
      if (eb(b2) || Ka(b2)) return b2 = Tg(b2, a2.mode, c2, null), b2.return = a2, b2;
      Mg(a2, b2);
    }
    return null;
  }
  function r2(a2, b2, c2, d2) {
    var e2 = null !== b2 ? b2.key : null;
    if ("string" === typeof c2 && "" !== c2 || "number" === typeof c2) return null !== e2 ? null : h2(a2, b2, "" + c2, d2);
    if ("object" === typeof c2 && null !== c2) {
      switch (c2.$$typeof) {
        case va:
          return c2.key === e2 ? k2(a2, b2, c2, d2) : null;
        case wa:
          return c2.key === e2 ? l2(a2, b2, c2, d2) : null;
        case Ha:
          return e2 = c2._init, r2(
            a2,
            b2,
            e2(c2._payload),
            d2
          );
      }
      if (eb(c2) || Ka(c2)) return null !== e2 ? null : m2(a2, b2, c2, d2, null);
      Mg(a2, c2);
    }
    return null;
  }
  function y2(a2, b2, c2, d2, e2) {
    if ("string" === typeof d2 && "" !== d2 || "number" === typeof d2) return a2 = a2.get(c2) || null, h2(b2, a2, "" + d2, e2);
    if ("object" === typeof d2 && null !== d2) {
      switch (d2.$$typeof) {
        case va:
          return a2 = a2.get(null === d2.key ? c2 : d2.key) || null, k2(b2, a2, d2, e2);
        case wa:
          return a2 = a2.get(null === d2.key ? c2 : d2.key) || null, l2(b2, a2, d2, e2);
        case Ha:
          var f3 = d2._init;
          return y2(a2, b2, c2, f3(d2._payload), e2);
      }
      if (eb(d2) || Ka(d2)) return a2 = a2.get(c2) || null, m2(b2, a2, d2, e2, null);
      Mg(b2, d2);
    }
    return null;
  }
  function n2(e2, g2, h3, k3) {
    for (var l3 = null, m3 = null, u2 = g2, w2 = g2 = 0, x2 = null; null !== u2 && w2 < h3.length; w2++) {
      u2.index > w2 ? (x2 = u2, u2 = null) : x2 = u2.sibling;
      var n3 = r2(e2, u2, h3[w2], k3);
      if (null === n3) {
        null === u2 && (u2 = x2);
        break;
      }
      a && u2 && null === n3.alternate && b(e2, u2);
      g2 = f2(n3, g2, w2);
      null === m3 ? l3 = n3 : m3.sibling = n3;
      m3 = n3;
      u2 = x2;
    }
    if (w2 === h3.length) return c(e2, u2), I && tg(e2, w2), l3;
    if (null === u2) {
      for (; w2 < h3.length; w2++) u2 = q2(e2, h3[w2], k3), null !== u2 && (g2 = f2(u2, g2, w2), null === m3 ? l3 = u2 : m3.sibling = u2, m3 = u2);
      I && tg(e2, w2);
      return l3;
    }
    for (u2 = d(e2, u2); w2 < h3.length; w2++) x2 = y2(u2, e2, w2, h3[w2], k3), null !== x2 && (a && null !== x2.alternate && u2.delete(null === x2.key ? w2 : x2.key), g2 = f2(x2, g2, w2), null === m3 ? l3 = x2 : m3.sibling = x2, m3 = x2);
    a && u2.forEach(function(a2) {
      return b(e2, a2);
    });
    I && tg(e2, w2);
    return l3;
  }
  function t2(e2, g2, h3, k3) {
    var l3 = Ka(h3);
    if ("function" !== typeof l3) throw Error(p(150));
    h3 = l3.call(h3);
    if (null == h3) throw Error(p(151));
    for (var u2 = l3 = null, m3 = g2, w2 = g2 = 0, x2 = null, n3 = h3.next(); null !== m3 && !n3.done; w2++, n3 = h3.next()) {
      m3.index > w2 ? (x2 = m3, m3 = null) : x2 = m3.sibling;
      var t3 = r2(e2, m3, n3.value, k3);
      if (null === t3) {
        null === m3 && (m3 = x2);
        break;
      }
      a && m3 && null === t3.alternate && b(e2, m3);
      g2 = f2(t3, g2, w2);
      null === u2 ? l3 = t3 : u2.sibling = t3;
      u2 = t3;
      m3 = x2;
    }
    if (n3.done) return c(
      e2,
      m3
    ), I && tg(e2, w2), l3;
    if (null === m3) {
      for (; !n3.done; w2++, n3 = h3.next()) n3 = q2(e2, n3.value, k3), null !== n3 && (g2 = f2(n3, g2, w2), null === u2 ? l3 = n3 : u2.sibling = n3, u2 = n3);
      I && tg(e2, w2);
      return l3;
    }
    for (m3 = d(e2, m3); !n3.done; w2++, n3 = h3.next()) n3 = y2(m3, e2, w2, n3.value, k3), null !== n3 && (a && null !== n3.alternate && m3.delete(null === n3.key ? w2 : n3.key), g2 = f2(n3, g2, w2), null === u2 ? l3 = n3 : u2.sibling = n3, u2 = n3);
    a && m3.forEach(function(a2) {
      return b(e2, a2);
    });
    I && tg(e2, w2);
    return l3;
  }
  function J2(a2, d2, f3, h3) {
    "object" === typeof f3 && null !== f3 && f3.type === ya && null === f3.key && (f3 = f3.props.children);
    if ("object" === typeof f3 && null !== f3) {
      switch (f3.$$typeof) {
        case va:
          a: {
            for (var k3 = f3.key, l3 = d2; null !== l3; ) {
              if (l3.key === k3) {
                k3 = f3.type;
                if (k3 === ya) {
                  if (7 === l3.tag) {
                    c(a2, l3.sibling);
                    d2 = e(l3, f3.props.children);
                    d2.return = a2;
                    a2 = d2;
                    break a;
                  }
                } else if (l3.elementType === k3 || "object" === typeof k3 && null !== k3 && k3.$$typeof === Ha && Ng(k3) === l3.type) {
                  c(a2, l3.sibling);
                  d2 = e(l3, f3.props);
                  d2.ref = Lg(a2, l3, f3);
                  d2.return = a2;
                  a2 = d2;
                  break a;
                }
                c(a2, l3);
                break;
              } else b(a2, l3);
              l3 = l3.sibling;
            }
            f3.type === ya ? (d2 = Tg(f3.props.children, a2.mode, h3, f3.key), d2.return = a2, a2 = d2) : (h3 = Rg(f3.type, f3.key, f3.props, null, a2.mode, h3), h3.ref = Lg(a2, d2, f3), h3.return = a2, a2 = h3);
          }
          return g(a2);
        case wa:
          a: {
            for (l3 = f3.key; null !== d2; ) {
              if (d2.key === l3) if (4 === d2.tag && d2.stateNode.containerInfo === f3.containerInfo && d2.stateNode.implementation === f3.implementation) {
                c(a2, d2.sibling);
                d2 = e(d2, f3.children || []);
                d2.return = a2;
                a2 = d2;
                break a;
              } else {
                c(a2, d2);
                break;
              }
              else b(a2, d2);
              d2 = d2.sibling;
            }
            d2 = Sg(f3, a2.mode, h3);
            d2.return = a2;
            a2 = d2;
          }
          return g(a2);
        case Ha:
          return l3 = f3._init, J2(a2, d2, l3(f3._payload), h3);
      }
      if (eb(f3)) return n2(a2, d2, f3, h3);
      if (Ka(f3)) return t2(a2, d2, f3, h3);
      Mg(a2, f3);
    }
    return "string" === typeof f3 && "" !== f3 || "number" === typeof f3 ? (f3 = "" + f3, null !== d2 && 6 === d2.tag ? (c(a2, d2.sibling), d2 = e(d2, f3), d2.return = a2, a2 = d2) : (c(a2, d2), d2 = Qg(f3, a2.mode, h3), d2.return = a2, a2 = d2), g(a2)) : c(a2, d2);
  }
  return J2;
}
var Ug = Og(true), Vg = Og(false), Wg = Uf(null), Xg = null, Yg = null, Zg = null;
function $g() {
  Zg = Yg = Xg = null;
}
function ah(a) {
  var b = Wg.current;
  E(Wg);
  a._currentValue = b;
}
function bh(a, b, c) {
  for (; null !== a; ) {
    var d = a.alternate;
    (a.childLanes & b) !== b ? (a.childLanes |= b, null !== d && (d.childLanes |= b)) : null !== d && (d.childLanes & b) !== b && (d.childLanes |= b);
    if (a === c) break;
    a = a.return;
  }
}
function ch(a, b) {
  Xg = a;
  Zg = Yg = null;
  a = a.dependencies;
  null !== a && null !== a.firstContext && (0 !== (a.lanes & b) && (dh = true), a.firstContext = null);
}
function eh(a) {
  var b = a._currentValue;
  if (Zg !== a) if (a = { context: a, memoizedValue: b, next: null }, null === Yg) {
    if (null === Xg) throw Error(p(308));
    Yg = a;
    Xg.dependencies = { lanes: 0, firstContext: a };
  } else Yg = Yg.next = a;
  return b;
}
var fh = null;
function gh(a) {
  null === fh ? fh = [a] : fh.push(a);
}
function hh(a, b, c, d) {
  var e = b.interleaved;
  null === e ? (c.next = c, gh(b)) : (c.next = e.next, e.next = c);
  b.interleaved = c;
  return ih(a, d);
}
function ih(a, b) {
  a.lanes |= b;
  var c = a.alternate;
  null !== c && (c.lanes |= b);
  c = a;
  for (a = a.return; null !== a; ) a.childLanes |= b, c = a.alternate, null !== c && (c.childLanes |= b), c = a, a = a.return;
  return 3 === c.tag ? c.stateNode : null;
}
var jh = false;
function kh(a) {
  a.updateQueue = { baseState: a.memoizedState, firstBaseUpdate: null, lastBaseUpdate: null, shared: { pending: null, interleaved: null, lanes: 0 }, effects: null };
}
function lh(a, b) {
  a = a.updateQueue;
  b.updateQueue === a && (b.updateQueue = { baseState: a.baseState, firstBaseUpdate: a.firstBaseUpdate, lastBaseUpdate: a.lastBaseUpdate, shared: a.shared, effects: a.effects });
}
function mh(a, b) {
  return { eventTime: a, lane: b, tag: 0, payload: null, callback: null, next: null };
}
function nh(a, b, c) {
  var d = a.updateQueue;
  if (null === d) return null;
  d = d.shared;
  if (0 !== (K & 2)) {
    var e = d.pending;
    null === e ? b.next = b : (b.next = e.next, e.next = b);
    d.pending = b;
    return ih(a, c);
  }
  e = d.interleaved;
  null === e ? (b.next = b, gh(d)) : (b.next = e.next, e.next = b);
  d.interleaved = b;
  return ih(a, c);
}
function oh(a, b, c) {
  b = b.updateQueue;
  if (null !== b && (b = b.shared, 0 !== (c & 4194240))) {
    var d = b.lanes;
    d &= a.pendingLanes;
    c |= d;
    b.lanes = c;
    Cc(a, c);
  }
}
function ph(a, b) {
  var c = a.updateQueue, d = a.alternate;
  if (null !== d && (d = d.updateQueue, c === d)) {
    var e = null, f2 = null;
    c = c.firstBaseUpdate;
    if (null !== c) {
      do {
        var g = { eventTime: c.eventTime, lane: c.lane, tag: c.tag, payload: c.payload, callback: c.callback, next: null };
        null === f2 ? e = f2 = g : f2 = f2.next = g;
        c = c.next;
      } while (null !== c);
      null === f2 ? e = f2 = b : f2 = f2.next = b;
    } else e = f2 = b;
    c = { baseState: d.baseState, firstBaseUpdate: e, lastBaseUpdate: f2, shared: d.shared, effects: d.effects };
    a.updateQueue = c;
    return;
  }
  a = c.lastBaseUpdate;
  null === a ? c.firstBaseUpdate = b : a.next = b;
  c.lastBaseUpdate = b;
}
function qh(a, b, c, d) {
  var e = a.updateQueue;
  jh = false;
  var f2 = e.firstBaseUpdate, g = e.lastBaseUpdate, h2 = e.shared.pending;
  if (null !== h2) {
    e.shared.pending = null;
    var k2 = h2, l2 = k2.next;
    k2.next = null;
    null === g ? f2 = l2 : g.next = l2;
    g = k2;
    var m2 = a.alternate;
    null !== m2 && (m2 = m2.updateQueue, h2 = m2.lastBaseUpdate, h2 !== g && (null === h2 ? m2.firstBaseUpdate = l2 : h2.next = l2, m2.lastBaseUpdate = k2));
  }
  if (null !== f2) {
    var q2 = e.baseState;
    g = 0;
    m2 = l2 = k2 = null;
    h2 = f2;
    do {
      var r2 = h2.lane, y2 = h2.eventTime;
      if ((d & r2) === r2) {
        null !== m2 && (m2 = m2.next = {
          eventTime: y2,
          lane: 0,
          tag: h2.tag,
          payload: h2.payload,
          callback: h2.callback,
          next: null
        });
        a: {
          var n2 = a, t2 = h2;
          r2 = b;
          y2 = c;
          switch (t2.tag) {
            case 1:
              n2 = t2.payload;
              if ("function" === typeof n2) {
                q2 = n2.call(y2, q2, r2);
                break a;
              }
              q2 = n2;
              break a;
            case 3:
              n2.flags = n2.flags & -65537 | 128;
            case 0:
              n2 = t2.payload;
              r2 = "function" === typeof n2 ? n2.call(y2, q2, r2) : n2;
              if (null === r2 || void 0 === r2) break a;
              q2 = A({}, q2, r2);
              break a;
            case 2:
              jh = true;
          }
        }
        null !== h2.callback && 0 !== h2.lane && (a.flags |= 64, r2 = e.effects, null === r2 ? e.effects = [h2] : r2.push(h2));
      } else y2 = { eventTime: y2, lane: r2, tag: h2.tag, payload: h2.payload, callback: h2.callback, next: null }, null === m2 ? (l2 = m2 = y2, k2 = q2) : m2 = m2.next = y2, g |= r2;
      h2 = h2.next;
      if (null === h2) if (h2 = e.shared.pending, null === h2) break;
      else r2 = h2, h2 = r2.next, r2.next = null, e.lastBaseUpdate = r2, e.shared.pending = null;
    } while (1);
    null === m2 && (k2 = q2);
    e.baseState = k2;
    e.firstBaseUpdate = l2;
    e.lastBaseUpdate = m2;
    b = e.shared.interleaved;
    if (null !== b) {
      e = b;
      do
        g |= e.lane, e = e.next;
      while (e !== b);
    } else null === f2 && (e.shared.lanes = 0);
    rh |= g;
    a.lanes = g;
    a.memoizedState = q2;
  }
}
function sh(a, b, c) {
  a = b.effects;
  b.effects = null;
  if (null !== a) for (b = 0; b < a.length; b++) {
    var d = a[b], e = d.callback;
    if (null !== e) {
      d.callback = null;
      d = c;
      if ("function" !== typeof e) throw Error(p(191, e));
      e.call(d);
    }
  }
}
var th = {}, uh = Uf(th), vh = Uf(th), wh = Uf(th);
function xh(a) {
  if (a === th) throw Error(p(174));
  return a;
}
function yh(a, b) {
  G(wh, b);
  G(vh, a);
  G(uh, th);
  a = b.nodeType;
  switch (a) {
    case 9:
    case 11:
      b = (b = b.documentElement) ? b.namespaceURI : lb(null, "");
      break;
    default:
      a = 8 === a ? b.parentNode : b, b = a.namespaceURI || null, a = a.tagName, b = lb(b, a);
  }
  E(uh);
  G(uh, b);
}
function zh() {
  E(uh);
  E(vh);
  E(wh);
}
function Ah(a) {
  xh(wh.current);
  var b = xh(uh.current);
  var c = lb(b, a.type);
  b !== c && (G(vh, a), G(uh, c));
}
function Bh(a) {
  vh.current === a && (E(uh), E(vh));
}
var L = Uf(0);
function Ch(a) {
  for (var b = a; null !== b; ) {
    if (13 === b.tag) {
      var c = b.memoizedState;
      if (null !== c && (c = c.dehydrated, null === c || "$?" === c.data || "$!" === c.data)) return b;
    } else if (19 === b.tag && void 0 !== b.memoizedProps.revealOrder) {
      if (0 !== (b.flags & 128)) return b;
    } else if (null !== b.child) {
      b.child.return = b;
      b = b.child;
      continue;
    }
    if (b === a) break;
    for (; null === b.sibling; ) {
      if (null === b.return || b.return === a) return null;
      b = b.return;
    }
    b.sibling.return = b.return;
    b = b.sibling;
  }
  return null;
}
var Dh = [];
function Eh() {
  for (var a = 0; a < Dh.length; a++) Dh[a]._workInProgressVersionPrimary = null;
  Dh.length = 0;
}
var Fh = ua.ReactCurrentDispatcher, Gh = ua.ReactCurrentBatchConfig, Hh = 0, M = null, N = null, O = null, Ih = false, Jh = false, Kh = 0, Lh = 0;
function P() {
  throw Error(p(321));
}
function Mh(a, b) {
  if (null === b) return false;
  for (var c = 0; c < b.length && c < a.length; c++) if (!He$1(a[c], b[c])) return false;
  return true;
}
function Nh(a, b, c, d, e, f2) {
  Hh = f2;
  M = b;
  b.memoizedState = null;
  b.updateQueue = null;
  b.lanes = 0;
  Fh.current = null === a || null === a.memoizedState ? Oh : Ph;
  a = c(d, e);
  if (Jh) {
    f2 = 0;
    do {
      Jh = false;
      Kh = 0;
      if (25 <= f2) throw Error(p(301));
      f2 += 1;
      O = N = null;
      b.updateQueue = null;
      Fh.current = Qh;
      a = c(d, e);
    } while (Jh);
  }
  Fh.current = Rh;
  b = null !== N && null !== N.next;
  Hh = 0;
  O = N = M = null;
  Ih = false;
  if (b) throw Error(p(300));
  return a;
}
function Sh() {
  var a = 0 !== Kh;
  Kh = 0;
  return a;
}
function Th() {
  var a = { memoizedState: null, baseState: null, baseQueue: null, queue: null, next: null };
  null === O ? M.memoizedState = O = a : O = O.next = a;
  return O;
}
function Uh() {
  if (null === N) {
    var a = M.alternate;
    a = null !== a ? a.memoizedState : null;
  } else a = N.next;
  var b = null === O ? M.memoizedState : O.next;
  if (null !== b) O = b, N = a;
  else {
    if (null === a) throw Error(p(310));
    N = a;
    a = { memoizedState: N.memoizedState, baseState: N.baseState, baseQueue: N.baseQueue, queue: N.queue, next: null };
    null === O ? M.memoizedState = O = a : O = O.next = a;
  }
  return O;
}
function Vh(a, b) {
  return "function" === typeof b ? b(a) : b;
}
function Wh(a) {
  var b = Uh(), c = b.queue;
  if (null === c) throw Error(p(311));
  c.lastRenderedReducer = a;
  var d = N, e = d.baseQueue, f2 = c.pending;
  if (null !== f2) {
    if (null !== e) {
      var g = e.next;
      e.next = f2.next;
      f2.next = g;
    }
    d.baseQueue = e = f2;
    c.pending = null;
  }
  if (null !== e) {
    f2 = e.next;
    d = d.baseState;
    var h2 = g = null, k2 = null, l2 = f2;
    do {
      var m2 = l2.lane;
      if ((Hh & m2) === m2) null !== k2 && (k2 = k2.next = { lane: 0, action: l2.action, hasEagerState: l2.hasEagerState, eagerState: l2.eagerState, next: null }), d = l2.hasEagerState ? l2.eagerState : a(d, l2.action);
      else {
        var q2 = {
          lane: m2,
          action: l2.action,
          hasEagerState: l2.hasEagerState,
          eagerState: l2.eagerState,
          next: null
        };
        null === k2 ? (h2 = k2 = q2, g = d) : k2 = k2.next = q2;
        M.lanes |= m2;
        rh |= m2;
      }
      l2 = l2.next;
    } while (null !== l2 && l2 !== f2);
    null === k2 ? g = d : k2.next = h2;
    He$1(d, b.memoizedState) || (dh = true);
    b.memoizedState = d;
    b.baseState = g;
    b.baseQueue = k2;
    c.lastRenderedState = d;
  }
  a = c.interleaved;
  if (null !== a) {
    e = a;
    do
      f2 = e.lane, M.lanes |= f2, rh |= f2, e = e.next;
    while (e !== a);
  } else null === e && (c.lanes = 0);
  return [b.memoizedState, c.dispatch];
}
function Xh(a) {
  var b = Uh(), c = b.queue;
  if (null === c) throw Error(p(311));
  c.lastRenderedReducer = a;
  var d = c.dispatch, e = c.pending, f2 = b.memoizedState;
  if (null !== e) {
    c.pending = null;
    var g = e = e.next;
    do
      f2 = a(f2, g.action), g = g.next;
    while (g !== e);
    He$1(f2, b.memoizedState) || (dh = true);
    b.memoizedState = f2;
    null === b.baseQueue && (b.baseState = f2);
    c.lastRenderedState = f2;
  }
  return [f2, d];
}
function Yh() {
}
function Zh(a, b) {
  var c = M, d = Uh(), e = b(), f2 = !He$1(d.memoizedState, e);
  f2 && (d.memoizedState = e, dh = true);
  d = d.queue;
  $h(ai.bind(null, c, d, a), [a]);
  if (d.getSnapshot !== b || f2 || null !== O && O.memoizedState.tag & 1) {
    c.flags |= 2048;
    bi(9, ci.bind(null, c, d, e, b), void 0, null);
    if (null === Q) throw Error(p(349));
    0 !== (Hh & 30) || di(c, b, e);
  }
  return e;
}
function di(a, b, c) {
  a.flags |= 16384;
  a = { getSnapshot: b, value: c };
  b = M.updateQueue;
  null === b ? (b = { lastEffect: null, stores: null }, M.updateQueue = b, b.stores = [a]) : (c = b.stores, null === c ? b.stores = [a] : c.push(a));
}
function ci(a, b, c, d) {
  b.value = c;
  b.getSnapshot = d;
  ei(b) && fi(a);
}
function ai(a, b, c) {
  return c(function() {
    ei(b) && fi(a);
  });
}
function ei(a) {
  var b = a.getSnapshot;
  a = a.value;
  try {
    var c = b();
    return !He$1(a, c);
  } catch (d) {
    return true;
  }
}
function fi(a) {
  var b = ih(a, 1);
  null !== b && gi(b, a, 1, -1);
}
function hi(a) {
  var b = Th();
  "function" === typeof a && (a = a());
  b.memoizedState = b.baseState = a;
  a = { pending: null, interleaved: null, lanes: 0, dispatch: null, lastRenderedReducer: Vh, lastRenderedState: a };
  b.queue = a;
  a = a.dispatch = ii.bind(null, M, a);
  return [b.memoizedState, a];
}
function bi(a, b, c, d) {
  a = { tag: a, create: b, destroy: c, deps: d, next: null };
  b = M.updateQueue;
  null === b ? (b = { lastEffect: null, stores: null }, M.updateQueue = b, b.lastEffect = a.next = a) : (c = b.lastEffect, null === c ? b.lastEffect = a.next = a : (d = c.next, c.next = a, a.next = d, b.lastEffect = a));
  return a;
}
function ji() {
  return Uh().memoizedState;
}
function ki(a, b, c, d) {
  var e = Th();
  M.flags |= a;
  e.memoizedState = bi(1 | b, c, void 0, void 0 === d ? null : d);
}
function li(a, b, c, d) {
  var e = Uh();
  d = void 0 === d ? null : d;
  var f2 = void 0;
  if (null !== N) {
    var g = N.memoizedState;
    f2 = g.destroy;
    if (null !== d && Mh(d, g.deps)) {
      e.memoizedState = bi(b, c, f2, d);
      return;
    }
  }
  M.flags |= a;
  e.memoizedState = bi(1 | b, c, f2, d);
}
function mi(a, b) {
  return ki(8390656, 8, a, b);
}
function $h(a, b) {
  return li(2048, 8, a, b);
}
function ni(a, b) {
  return li(4, 2, a, b);
}
function oi(a, b) {
  return li(4, 4, a, b);
}
function pi(a, b) {
  if ("function" === typeof b) return a = a(), b(a), function() {
    b(null);
  };
  if (null !== b && void 0 !== b) return a = a(), b.current = a, function() {
    b.current = null;
  };
}
function qi(a, b, c) {
  c = null !== c && void 0 !== c ? c.concat([a]) : null;
  return li(4, 4, pi.bind(null, b, a), c);
}
function ri() {
}
function si(a, b) {
  var c = Uh();
  b = void 0 === b ? null : b;
  var d = c.memoizedState;
  if (null !== d && null !== b && Mh(b, d[1])) return d[0];
  c.memoizedState = [a, b];
  return a;
}
function ti(a, b) {
  var c = Uh();
  b = void 0 === b ? null : b;
  var d = c.memoizedState;
  if (null !== d && null !== b && Mh(b, d[1])) return d[0];
  a = a();
  c.memoizedState = [a, b];
  return a;
}
function ui(a, b, c) {
  if (0 === (Hh & 21)) return a.baseState && (a.baseState = false, dh = true), a.memoizedState = c;
  He$1(c, b) || (c = yc(), M.lanes |= c, rh |= c, a.baseState = true);
  return b;
}
function vi(a, b) {
  var c = C;
  C = 0 !== c && 4 > c ? c : 4;
  a(true);
  var d = Gh.transition;
  Gh.transition = {};
  try {
    a(false), b();
  } finally {
    C = c, Gh.transition = d;
  }
}
function wi() {
  return Uh().memoizedState;
}
function xi(a, b, c) {
  var d = yi(a);
  c = { lane: d, action: c, hasEagerState: false, eagerState: null, next: null };
  if (zi(a)) Ai(b, c);
  else if (c = hh(a, b, c, d), null !== c) {
    var e = R();
    gi(c, a, d, e);
    Bi(c, b, d);
  }
}
function ii(a, b, c) {
  var d = yi(a), e = { lane: d, action: c, hasEagerState: false, eagerState: null, next: null };
  if (zi(a)) Ai(b, e);
  else {
    var f2 = a.alternate;
    if (0 === a.lanes && (null === f2 || 0 === f2.lanes) && (f2 = b.lastRenderedReducer, null !== f2)) try {
      var g = b.lastRenderedState, h2 = f2(g, c);
      e.hasEagerState = true;
      e.eagerState = h2;
      if (He$1(h2, g)) {
        var k2 = b.interleaved;
        null === k2 ? (e.next = e, gh(b)) : (e.next = k2.next, k2.next = e);
        b.interleaved = e;
        return;
      }
    } catch (l2) {
    } finally {
    }
    c = hh(a, b, e, d);
    null !== c && (e = R(), gi(c, a, d, e), Bi(c, b, d));
  }
}
function zi(a) {
  var b = a.alternate;
  return a === M || null !== b && b === M;
}
function Ai(a, b) {
  Jh = Ih = true;
  var c = a.pending;
  null === c ? b.next = b : (b.next = c.next, c.next = b);
  a.pending = b;
}
function Bi(a, b, c) {
  if (0 !== (c & 4194240)) {
    var d = b.lanes;
    d &= a.pendingLanes;
    c |= d;
    b.lanes = c;
    Cc(a, c);
  }
}
var Rh = { readContext: eh, useCallback: P, useContext: P, useEffect: P, useImperativeHandle: P, useInsertionEffect: P, useLayoutEffect: P, useMemo: P, useReducer: P, useRef: P, useState: P, useDebugValue: P, useDeferredValue: P, useTransition: P, useMutableSource: P, useSyncExternalStore: P, useId: P, unstable_isNewReconciler: false }, Oh = { readContext: eh, useCallback: function(a, b) {
  Th().memoizedState = [a, void 0 === b ? null : b];
  return a;
}, useContext: eh, useEffect: mi, useImperativeHandle: function(a, b, c) {
  c = null !== c && void 0 !== c ? c.concat([a]) : null;
  return ki(
    4194308,
    4,
    pi.bind(null, b, a),
    c
  );
}, useLayoutEffect: function(a, b) {
  return ki(4194308, 4, a, b);
}, useInsertionEffect: function(a, b) {
  return ki(4, 2, a, b);
}, useMemo: function(a, b) {
  var c = Th();
  b = void 0 === b ? null : b;
  a = a();
  c.memoizedState = [a, b];
  return a;
}, useReducer: function(a, b, c) {
  var d = Th();
  b = void 0 !== c ? c(b) : b;
  d.memoizedState = d.baseState = b;
  a = { pending: null, interleaved: null, lanes: 0, dispatch: null, lastRenderedReducer: a, lastRenderedState: b };
  d.queue = a;
  a = a.dispatch = xi.bind(null, M, a);
  return [d.memoizedState, a];
}, useRef: function(a) {
  var b = Th();
  a = { current: a };
  return b.memoizedState = a;
}, useState: hi, useDebugValue: ri, useDeferredValue: function(a) {
  return Th().memoizedState = a;
}, useTransition: function() {
  var a = hi(false), b = a[0];
  a = vi.bind(null, a[1]);
  Th().memoizedState = a;
  return [b, a];
}, useMutableSource: function() {
}, useSyncExternalStore: function(a, b, c) {
  var d = M, e = Th();
  if (I) {
    if (void 0 === c) throw Error(p(407));
    c = c();
  } else {
    c = b();
    if (null === Q) throw Error(p(349));
    0 !== (Hh & 30) || di(d, b, c);
  }
  e.memoizedState = c;
  var f2 = { value: c, getSnapshot: b };
  e.queue = f2;
  mi(ai.bind(
    null,
    d,
    f2,
    a
  ), [a]);
  d.flags |= 2048;
  bi(9, ci.bind(null, d, f2, c, b), void 0, null);
  return c;
}, useId: function() {
  var a = Th(), b = Q.identifierPrefix;
  if (I) {
    var c = sg;
    var d = rg;
    c = (d & ~(1 << 32 - oc(d) - 1)).toString(32) + c;
    b = ":" + b + "R" + c;
    c = Kh++;
    0 < c && (b += "H" + c.toString(32));
    b += ":";
  } else c = Lh++, b = ":" + b + "r" + c.toString(32) + ":";
  return a.memoizedState = b;
}, unstable_isNewReconciler: false }, Ph = {
  readContext: eh,
  useCallback: si,
  useContext: eh,
  useEffect: $h,
  useImperativeHandle: qi,
  useInsertionEffect: ni,
  useLayoutEffect: oi,
  useMemo: ti,
  useReducer: Wh,
  useRef: ji,
  useState: function() {
    return Wh(Vh);
  },
  useDebugValue: ri,
  useDeferredValue: function(a) {
    var b = Uh();
    return ui(b, N.memoizedState, a);
  },
  useTransition: function() {
    var a = Wh(Vh)[0], b = Uh().memoizedState;
    return [a, b];
  },
  useMutableSource: Yh,
  useSyncExternalStore: Zh,
  useId: wi,
  unstable_isNewReconciler: false
}, Qh = { readContext: eh, useCallback: si, useContext: eh, useEffect: $h, useImperativeHandle: qi, useInsertionEffect: ni, useLayoutEffect: oi, useMemo: ti, useReducer: Xh, useRef: ji, useState: function() {
  return Xh(Vh);
}, useDebugValue: ri, useDeferredValue: function(a) {
  var b = Uh();
  return null === N ? b.memoizedState = a : ui(b, N.memoizedState, a);
}, useTransition: function() {
  var a = Xh(Vh)[0], b = Uh().memoizedState;
  return [a, b];
}, useMutableSource: Yh, useSyncExternalStore: Zh, useId: wi, unstable_isNewReconciler: false };
function Ci(a, b) {
  if (a && a.defaultProps) {
    b = A({}, b);
    a = a.defaultProps;
    for (var c in a) void 0 === b[c] && (b[c] = a[c]);
    return b;
  }
  return b;
}
function Di(a, b, c, d) {
  b = a.memoizedState;
  c = c(d, b);
  c = null === c || void 0 === c ? b : A({}, b, c);
  a.memoizedState = c;
  0 === a.lanes && (a.updateQueue.baseState = c);
}
var Ei = { isMounted: function(a) {
  return (a = a._reactInternals) ? Vb(a) === a : false;
}, enqueueSetState: function(a, b, c) {
  a = a._reactInternals;
  var d = R(), e = yi(a), f2 = mh(d, e);
  f2.payload = b;
  void 0 !== c && null !== c && (f2.callback = c);
  b = nh(a, f2, e);
  null !== b && (gi(b, a, e, d), oh(b, a, e));
}, enqueueReplaceState: function(a, b, c) {
  a = a._reactInternals;
  var d = R(), e = yi(a), f2 = mh(d, e);
  f2.tag = 1;
  f2.payload = b;
  void 0 !== c && null !== c && (f2.callback = c);
  b = nh(a, f2, e);
  null !== b && (gi(b, a, e, d), oh(b, a, e));
}, enqueueForceUpdate: function(a, b) {
  a = a._reactInternals;
  var c = R(), d = yi(a), e = mh(c, d);
  e.tag = 2;
  void 0 !== b && null !== b && (e.callback = b);
  b = nh(a, e, d);
  null !== b && (gi(b, a, d, c), oh(b, a, d));
} };
function Fi(a, b, c, d, e, f2, g) {
  a = a.stateNode;
  return "function" === typeof a.shouldComponentUpdate ? a.shouldComponentUpdate(d, f2, g) : b.prototype && b.prototype.isPureReactComponent ? !Ie(c, d) || !Ie(e, f2) : true;
}
function Gi(a, b, c) {
  var d = false, e = Vf;
  var f2 = b.contextType;
  "object" === typeof f2 && null !== f2 ? f2 = eh(f2) : (e = Zf(b) ? Xf : H$1.current, d = b.contextTypes, f2 = (d = null !== d && void 0 !== d) ? Yf(a, e) : Vf);
  b = new b(c, f2);
  a.memoizedState = null !== b.state && void 0 !== b.state ? b.state : null;
  b.updater = Ei;
  a.stateNode = b;
  b._reactInternals = a;
  d && (a = a.stateNode, a.__reactInternalMemoizedUnmaskedChildContext = e, a.__reactInternalMemoizedMaskedChildContext = f2);
  return b;
}
function Hi(a, b, c, d) {
  a = b.state;
  "function" === typeof b.componentWillReceiveProps && b.componentWillReceiveProps(c, d);
  "function" === typeof b.UNSAFE_componentWillReceiveProps && b.UNSAFE_componentWillReceiveProps(c, d);
  b.state !== a && Ei.enqueueReplaceState(b, b.state, null);
}
function Ii(a, b, c, d) {
  var e = a.stateNode;
  e.props = c;
  e.state = a.memoizedState;
  e.refs = {};
  kh(a);
  var f2 = b.contextType;
  "object" === typeof f2 && null !== f2 ? e.context = eh(f2) : (f2 = Zf(b) ? Xf : H$1.current, e.context = Yf(a, f2));
  e.state = a.memoizedState;
  f2 = b.getDerivedStateFromProps;
  "function" === typeof f2 && (Di(a, b, f2, c), e.state = a.memoizedState);
  "function" === typeof b.getDerivedStateFromProps || "function" === typeof e.getSnapshotBeforeUpdate || "function" !== typeof e.UNSAFE_componentWillMount && "function" !== typeof e.componentWillMount || (b = e.state, "function" === typeof e.componentWillMount && e.componentWillMount(), "function" === typeof e.UNSAFE_componentWillMount && e.UNSAFE_componentWillMount(), b !== e.state && Ei.enqueueReplaceState(e, e.state, null), qh(a, c, e, d), e.state = a.memoizedState);
  "function" === typeof e.componentDidMount && (a.flags |= 4194308);
}
function Ji(a, b) {
  try {
    var c = "", d = b;
    do
      c += Pa(d), d = d.return;
    while (d);
    var e = c;
  } catch (f2) {
    e = "\nError generating stack: " + f2.message + "\n" + f2.stack;
  }
  return { value: a, source: b, stack: e, digest: null };
}
function Ki(a, b, c) {
  return { value: a, source: null, stack: null != c ? c : null, digest: null != b ? b : null };
}
function Li(a, b) {
  try {
    console.error(b.value);
  } catch (c) {
    setTimeout(function() {
      throw c;
    });
  }
}
var Mi = "function" === typeof WeakMap ? WeakMap : Map;
function Ni(a, b, c) {
  c = mh(-1, c);
  c.tag = 3;
  c.payload = { element: null };
  var d = b.value;
  c.callback = function() {
    Oi || (Oi = true, Pi = d);
    Li(a, b);
  };
  return c;
}
function Qi(a, b, c) {
  c = mh(-1, c);
  c.tag = 3;
  var d = a.type.getDerivedStateFromError;
  if ("function" === typeof d) {
    var e = b.value;
    c.payload = function() {
      return d(e);
    };
    c.callback = function() {
      Li(a, b);
    };
  }
  var f2 = a.stateNode;
  null !== f2 && "function" === typeof f2.componentDidCatch && (c.callback = function() {
    Li(a, b);
    "function" !== typeof d && (null === Ri ? Ri = /* @__PURE__ */ new Set([this]) : Ri.add(this));
    var c2 = b.stack;
    this.componentDidCatch(b.value, { componentStack: null !== c2 ? c2 : "" });
  });
  return c;
}
function Si(a, b, c) {
  var d = a.pingCache;
  if (null === d) {
    d = a.pingCache = new Mi();
    var e = /* @__PURE__ */ new Set();
    d.set(b, e);
  } else e = d.get(b), void 0 === e && (e = /* @__PURE__ */ new Set(), d.set(b, e));
  e.has(c) || (e.add(c), a = Ti.bind(null, a, b, c), b.then(a, a));
}
function Ui(a) {
  do {
    var b;
    if (b = 13 === a.tag) b = a.memoizedState, b = null !== b ? null !== b.dehydrated ? true : false : true;
    if (b) return a;
    a = a.return;
  } while (null !== a);
  return null;
}
function Vi(a, b, c, d, e) {
  if (0 === (a.mode & 1)) return a === b ? a.flags |= 65536 : (a.flags |= 128, c.flags |= 131072, c.flags &= -52805, 1 === c.tag && (null === c.alternate ? c.tag = 17 : (b = mh(-1, 1), b.tag = 2, nh(c, b, 1))), c.lanes |= 1), a;
  a.flags |= 65536;
  a.lanes = e;
  return a;
}
var Wi = ua.ReactCurrentOwner, dh = false;
function Xi(a, b, c, d) {
  b.child = null === a ? Vg(b, null, c, d) : Ug(b, a.child, c, d);
}
function Yi(a, b, c, d, e) {
  c = c.render;
  var f2 = b.ref;
  ch(b, e);
  d = Nh(a, b, c, d, f2, e);
  c = Sh();
  if (null !== a && !dh) return b.updateQueue = a.updateQueue, b.flags &= -2053, a.lanes &= ~e, Zi(a, b, e);
  I && c && vg(b);
  b.flags |= 1;
  Xi(a, b, d, e);
  return b.child;
}
function $i(a, b, c, d, e) {
  if (null === a) {
    var f2 = c.type;
    if ("function" === typeof f2 && !aj(f2) && void 0 === f2.defaultProps && null === c.compare && void 0 === c.defaultProps) return b.tag = 15, b.type = f2, bj(a, b, f2, d, e);
    a = Rg(c.type, null, d, b, b.mode, e);
    a.ref = b.ref;
    a.return = b;
    return b.child = a;
  }
  f2 = a.child;
  if (0 === (a.lanes & e)) {
    var g = f2.memoizedProps;
    c = c.compare;
    c = null !== c ? c : Ie;
    if (c(g, d) && a.ref === b.ref) return Zi(a, b, e);
  }
  b.flags |= 1;
  a = Pg(f2, d);
  a.ref = b.ref;
  a.return = b;
  return b.child = a;
}
function bj(a, b, c, d, e) {
  if (null !== a) {
    var f2 = a.memoizedProps;
    if (Ie(f2, d) && a.ref === b.ref) if (dh = false, b.pendingProps = d = f2, 0 !== (a.lanes & e)) 0 !== (a.flags & 131072) && (dh = true);
    else return b.lanes = a.lanes, Zi(a, b, e);
  }
  return cj(a, b, c, d, e);
}
function dj(a, b, c) {
  var d = b.pendingProps, e = d.children, f2 = null !== a ? a.memoizedState : null;
  if ("hidden" === d.mode) if (0 === (b.mode & 1)) b.memoizedState = { baseLanes: 0, cachePool: null, transitions: null }, G(ej, fj), fj |= c;
  else {
    if (0 === (c & 1073741824)) return a = null !== f2 ? f2.baseLanes | c : c, b.lanes = b.childLanes = 1073741824, b.memoizedState = { baseLanes: a, cachePool: null, transitions: null }, b.updateQueue = null, G(ej, fj), fj |= a, null;
    b.memoizedState = { baseLanes: 0, cachePool: null, transitions: null };
    d = null !== f2 ? f2.baseLanes : c;
    G(ej, fj);
    fj |= d;
  }
  else null !== f2 ? (d = f2.baseLanes | c, b.memoizedState = null) : d = c, G(ej, fj), fj |= d;
  Xi(a, b, e, c);
  return b.child;
}
function gj(a, b) {
  var c = b.ref;
  if (null === a && null !== c || null !== a && a.ref !== c) b.flags |= 512, b.flags |= 2097152;
}
function cj(a, b, c, d, e) {
  var f2 = Zf(c) ? Xf : H$1.current;
  f2 = Yf(b, f2);
  ch(b, e);
  c = Nh(a, b, c, d, f2, e);
  d = Sh();
  if (null !== a && !dh) return b.updateQueue = a.updateQueue, b.flags &= -2053, a.lanes &= ~e, Zi(a, b, e);
  I && d && vg(b);
  b.flags |= 1;
  Xi(a, b, c, e);
  return b.child;
}
function hj(a, b, c, d, e) {
  if (Zf(c)) {
    var f2 = true;
    cg(b);
  } else f2 = false;
  ch(b, e);
  if (null === b.stateNode) ij(a, b), Gi(b, c, d), Ii(b, c, d, e), d = true;
  else if (null === a) {
    var g = b.stateNode, h2 = b.memoizedProps;
    g.props = h2;
    var k2 = g.context, l2 = c.contextType;
    "object" === typeof l2 && null !== l2 ? l2 = eh(l2) : (l2 = Zf(c) ? Xf : H$1.current, l2 = Yf(b, l2));
    var m2 = c.getDerivedStateFromProps, q2 = "function" === typeof m2 || "function" === typeof g.getSnapshotBeforeUpdate;
    q2 || "function" !== typeof g.UNSAFE_componentWillReceiveProps && "function" !== typeof g.componentWillReceiveProps || (h2 !== d || k2 !== l2) && Hi(b, g, d, l2);
    jh = false;
    var r2 = b.memoizedState;
    g.state = r2;
    qh(b, d, g, e);
    k2 = b.memoizedState;
    h2 !== d || r2 !== k2 || Wf.current || jh ? ("function" === typeof m2 && (Di(b, c, m2, d), k2 = b.memoizedState), (h2 = jh || Fi(b, c, h2, d, r2, k2, l2)) ? (q2 || "function" !== typeof g.UNSAFE_componentWillMount && "function" !== typeof g.componentWillMount || ("function" === typeof g.componentWillMount && g.componentWillMount(), "function" === typeof g.UNSAFE_componentWillMount && g.UNSAFE_componentWillMount()), "function" === typeof g.componentDidMount && (b.flags |= 4194308)) : ("function" === typeof g.componentDidMount && (b.flags |= 4194308), b.memoizedProps = d, b.memoizedState = k2), g.props = d, g.state = k2, g.context = l2, d = h2) : ("function" === typeof g.componentDidMount && (b.flags |= 4194308), d = false);
  } else {
    g = b.stateNode;
    lh(a, b);
    h2 = b.memoizedProps;
    l2 = b.type === b.elementType ? h2 : Ci(b.type, h2);
    g.props = l2;
    q2 = b.pendingProps;
    r2 = g.context;
    k2 = c.contextType;
    "object" === typeof k2 && null !== k2 ? k2 = eh(k2) : (k2 = Zf(c) ? Xf : H$1.current, k2 = Yf(b, k2));
    var y2 = c.getDerivedStateFromProps;
    (m2 = "function" === typeof y2 || "function" === typeof g.getSnapshotBeforeUpdate) || "function" !== typeof g.UNSAFE_componentWillReceiveProps && "function" !== typeof g.componentWillReceiveProps || (h2 !== q2 || r2 !== k2) && Hi(b, g, d, k2);
    jh = false;
    r2 = b.memoizedState;
    g.state = r2;
    qh(b, d, g, e);
    var n2 = b.memoizedState;
    h2 !== q2 || r2 !== n2 || Wf.current || jh ? ("function" === typeof y2 && (Di(b, c, y2, d), n2 = b.memoizedState), (l2 = jh || Fi(b, c, l2, d, r2, n2, k2) || false) ? (m2 || "function" !== typeof g.UNSAFE_componentWillUpdate && "function" !== typeof g.componentWillUpdate || ("function" === typeof g.componentWillUpdate && g.componentWillUpdate(d, n2, k2), "function" === typeof g.UNSAFE_componentWillUpdate && g.UNSAFE_componentWillUpdate(d, n2, k2)), "function" === typeof g.componentDidUpdate && (b.flags |= 4), "function" === typeof g.getSnapshotBeforeUpdate && (b.flags |= 1024)) : ("function" !== typeof g.componentDidUpdate || h2 === a.memoizedProps && r2 === a.memoizedState || (b.flags |= 4), "function" !== typeof g.getSnapshotBeforeUpdate || h2 === a.memoizedProps && r2 === a.memoizedState || (b.flags |= 1024), b.memoizedProps = d, b.memoizedState = n2), g.props = d, g.state = n2, g.context = k2, d = l2) : ("function" !== typeof g.componentDidUpdate || h2 === a.memoizedProps && r2 === a.memoizedState || (b.flags |= 4), "function" !== typeof g.getSnapshotBeforeUpdate || h2 === a.memoizedProps && r2 === a.memoizedState || (b.flags |= 1024), d = false);
  }
  return jj(a, b, c, d, f2, e);
}
function jj(a, b, c, d, e, f2) {
  gj(a, b);
  var g = 0 !== (b.flags & 128);
  if (!d && !g) return e && dg(b, c, false), Zi(a, b, f2);
  d = b.stateNode;
  Wi.current = b;
  var h2 = g && "function" !== typeof c.getDerivedStateFromError ? null : d.render();
  b.flags |= 1;
  null !== a && g ? (b.child = Ug(b, a.child, null, f2), b.child = Ug(b, null, h2, f2)) : Xi(a, b, h2, f2);
  b.memoizedState = d.state;
  e && dg(b, c, true);
  return b.child;
}
function kj(a) {
  var b = a.stateNode;
  b.pendingContext ? ag(a, b.pendingContext, b.pendingContext !== b.context) : b.context && ag(a, b.context, false);
  yh(a, b.containerInfo);
}
function lj(a, b, c, d, e) {
  Ig();
  Jg(e);
  b.flags |= 256;
  Xi(a, b, c, d);
  return b.child;
}
var mj = { dehydrated: null, treeContext: null, retryLane: 0 };
function nj(a) {
  return { baseLanes: a, cachePool: null, transitions: null };
}
function oj(a, b, c) {
  var d = b.pendingProps, e = L.current, f2 = false, g = 0 !== (b.flags & 128), h2;
  (h2 = g) || (h2 = null !== a && null === a.memoizedState ? false : 0 !== (e & 2));
  if (h2) f2 = true, b.flags &= -129;
  else if (null === a || null !== a.memoizedState) e |= 1;
  G(L, e & 1);
  if (null === a) {
    Eg(b);
    a = b.memoizedState;
    if (null !== a && (a = a.dehydrated, null !== a)) return 0 === (b.mode & 1) ? b.lanes = 1 : "$!" === a.data ? b.lanes = 8 : b.lanes = 1073741824, null;
    g = d.children;
    a = d.fallback;
    return f2 ? (d = b.mode, f2 = b.child, g = { mode: "hidden", children: g }, 0 === (d & 1) && null !== f2 ? (f2.childLanes = 0, f2.pendingProps = g) : f2 = pj(g, d, 0, null), a = Tg(a, d, c, null), f2.return = b, a.return = b, f2.sibling = a, b.child = f2, b.child.memoizedState = nj(c), b.memoizedState = mj, a) : qj(b, g);
  }
  e = a.memoizedState;
  if (null !== e && (h2 = e.dehydrated, null !== h2)) return rj(a, b, g, d, h2, e, c);
  if (f2) {
    f2 = d.fallback;
    g = b.mode;
    e = a.child;
    h2 = e.sibling;
    var k2 = { mode: "hidden", children: d.children };
    0 === (g & 1) && b.child !== e ? (d = b.child, d.childLanes = 0, d.pendingProps = k2, b.deletions = null) : (d = Pg(e, k2), d.subtreeFlags = e.subtreeFlags & 14680064);
    null !== h2 ? f2 = Pg(h2, f2) : (f2 = Tg(f2, g, c, null), f2.flags |= 2);
    f2.return = b;
    d.return = b;
    d.sibling = f2;
    b.child = d;
    d = f2;
    f2 = b.child;
    g = a.child.memoizedState;
    g = null === g ? nj(c) : { baseLanes: g.baseLanes | c, cachePool: null, transitions: g.transitions };
    f2.memoizedState = g;
    f2.childLanes = a.childLanes & ~c;
    b.memoizedState = mj;
    return d;
  }
  f2 = a.child;
  a = f2.sibling;
  d = Pg(f2, { mode: "visible", children: d.children });
  0 === (b.mode & 1) && (d.lanes = c);
  d.return = b;
  d.sibling = null;
  null !== a && (c = b.deletions, null === c ? (b.deletions = [a], b.flags |= 16) : c.push(a));
  b.child = d;
  b.memoizedState = null;
  return d;
}
function qj(a, b) {
  b = pj({ mode: "visible", children: b }, a.mode, 0, null);
  b.return = a;
  return a.child = b;
}
function sj(a, b, c, d) {
  null !== d && Jg(d);
  Ug(b, a.child, null, c);
  a = qj(b, b.pendingProps.children);
  a.flags |= 2;
  b.memoizedState = null;
  return a;
}
function rj(a, b, c, d, e, f2, g) {
  if (c) {
    if (b.flags & 256) return b.flags &= -257, d = Ki(Error(p(422))), sj(a, b, g, d);
    if (null !== b.memoizedState) return b.child = a.child, b.flags |= 128, null;
    f2 = d.fallback;
    e = b.mode;
    d = pj({ mode: "visible", children: d.children }, e, 0, null);
    f2 = Tg(f2, e, g, null);
    f2.flags |= 2;
    d.return = b;
    f2.return = b;
    d.sibling = f2;
    b.child = d;
    0 !== (b.mode & 1) && Ug(b, a.child, null, g);
    b.child.memoizedState = nj(g);
    b.memoizedState = mj;
    return f2;
  }
  if (0 === (b.mode & 1)) return sj(a, b, g, null);
  if ("$!" === e.data) {
    d = e.nextSibling && e.nextSibling.dataset;
    if (d) var h2 = d.dgst;
    d = h2;
    f2 = Error(p(419));
    d = Ki(f2, d, void 0);
    return sj(a, b, g, d);
  }
  h2 = 0 !== (g & a.childLanes);
  if (dh || h2) {
    d = Q;
    if (null !== d) {
      switch (g & -g) {
        case 4:
          e = 2;
          break;
        case 16:
          e = 8;
          break;
        case 64:
        case 128:
        case 256:
        case 512:
        case 1024:
        case 2048:
        case 4096:
        case 8192:
        case 16384:
        case 32768:
        case 65536:
        case 131072:
        case 262144:
        case 524288:
        case 1048576:
        case 2097152:
        case 4194304:
        case 8388608:
        case 16777216:
        case 33554432:
        case 67108864:
          e = 32;
          break;
        case 536870912:
          e = 268435456;
          break;
        default:
          e = 0;
      }
      e = 0 !== (e & (d.suspendedLanes | g)) ? 0 : e;
      0 !== e && e !== f2.retryLane && (f2.retryLane = e, ih(a, e), gi(d, a, e, -1));
    }
    tj();
    d = Ki(Error(p(421)));
    return sj(a, b, g, d);
  }
  if ("$?" === e.data) return b.flags |= 128, b.child = a.child, b = uj.bind(null, a), e._reactRetry = b, null;
  a = f2.treeContext;
  yg = Lf(e.nextSibling);
  xg = b;
  I = true;
  zg = null;
  null !== a && (og[pg++] = rg, og[pg++] = sg, og[pg++] = qg, rg = a.id, sg = a.overflow, qg = b);
  b = qj(b, d.children);
  b.flags |= 4096;
  return b;
}
function vj(a, b, c) {
  a.lanes |= b;
  var d = a.alternate;
  null !== d && (d.lanes |= b);
  bh(a.return, b, c);
}
function wj(a, b, c, d, e) {
  var f2 = a.memoizedState;
  null === f2 ? a.memoizedState = { isBackwards: b, rendering: null, renderingStartTime: 0, last: d, tail: c, tailMode: e } : (f2.isBackwards = b, f2.rendering = null, f2.renderingStartTime = 0, f2.last = d, f2.tail = c, f2.tailMode = e);
}
function xj(a, b, c) {
  var d = b.pendingProps, e = d.revealOrder, f2 = d.tail;
  Xi(a, b, d.children, c);
  d = L.current;
  if (0 !== (d & 2)) d = d & 1 | 2, b.flags |= 128;
  else {
    if (null !== a && 0 !== (a.flags & 128)) a: for (a = b.child; null !== a; ) {
      if (13 === a.tag) null !== a.memoizedState && vj(a, c, b);
      else if (19 === a.tag) vj(a, c, b);
      else if (null !== a.child) {
        a.child.return = a;
        a = a.child;
        continue;
      }
      if (a === b) break a;
      for (; null === a.sibling; ) {
        if (null === a.return || a.return === b) break a;
        a = a.return;
      }
      a.sibling.return = a.return;
      a = a.sibling;
    }
    d &= 1;
  }
  G(L, d);
  if (0 === (b.mode & 1)) b.memoizedState = null;
  else switch (e) {
    case "forwards":
      c = b.child;
      for (e = null; null !== c; ) a = c.alternate, null !== a && null === Ch(a) && (e = c), c = c.sibling;
      c = e;
      null === c ? (e = b.child, b.child = null) : (e = c.sibling, c.sibling = null);
      wj(b, false, e, c, f2);
      break;
    case "backwards":
      c = null;
      e = b.child;
      for (b.child = null; null !== e; ) {
        a = e.alternate;
        if (null !== a && null === Ch(a)) {
          b.child = e;
          break;
        }
        a = e.sibling;
        e.sibling = c;
        c = e;
        e = a;
      }
      wj(b, true, c, null, f2);
      break;
    case "together":
      wj(b, false, null, null, void 0);
      break;
    default:
      b.memoizedState = null;
  }
  return b.child;
}
function ij(a, b) {
  0 === (b.mode & 1) && null !== a && (a.alternate = null, b.alternate = null, b.flags |= 2);
}
function Zi(a, b, c) {
  null !== a && (b.dependencies = a.dependencies);
  rh |= b.lanes;
  if (0 === (c & b.childLanes)) return null;
  if (null !== a && b.child !== a.child) throw Error(p(153));
  if (null !== b.child) {
    a = b.child;
    c = Pg(a, a.pendingProps);
    b.child = c;
    for (c.return = b; null !== a.sibling; ) a = a.sibling, c = c.sibling = Pg(a, a.pendingProps), c.return = b;
    c.sibling = null;
  }
  return b.child;
}
function yj(a, b, c) {
  switch (b.tag) {
    case 3:
      kj(b);
      Ig();
      break;
    case 5:
      Ah(b);
      break;
    case 1:
      Zf(b.type) && cg(b);
      break;
    case 4:
      yh(b, b.stateNode.containerInfo);
      break;
    case 10:
      var d = b.type._context, e = b.memoizedProps.value;
      G(Wg, d._currentValue);
      d._currentValue = e;
      break;
    case 13:
      d = b.memoizedState;
      if (null !== d) {
        if (null !== d.dehydrated) return G(L, L.current & 1), b.flags |= 128, null;
        if (0 !== (c & b.child.childLanes)) return oj(a, b, c);
        G(L, L.current & 1);
        a = Zi(a, b, c);
        return null !== a ? a.sibling : null;
      }
      G(L, L.current & 1);
      break;
    case 19:
      d = 0 !== (c & b.childLanes);
      if (0 !== (a.flags & 128)) {
        if (d) return xj(a, b, c);
        b.flags |= 128;
      }
      e = b.memoizedState;
      null !== e && (e.rendering = null, e.tail = null, e.lastEffect = null);
      G(L, L.current);
      if (d) break;
      else return null;
    case 22:
    case 23:
      return b.lanes = 0, dj(a, b, c);
  }
  return Zi(a, b, c);
}
var zj, Aj, Bj, Cj;
zj = function(a, b) {
  for (var c = b.child; null !== c; ) {
    if (5 === c.tag || 6 === c.tag) a.appendChild(c.stateNode);
    else if (4 !== c.tag && null !== c.child) {
      c.child.return = c;
      c = c.child;
      continue;
    }
    if (c === b) break;
    for (; null === c.sibling; ) {
      if (null === c.return || c.return === b) return;
      c = c.return;
    }
    c.sibling.return = c.return;
    c = c.sibling;
  }
};
Aj = function() {
};
Bj = function(a, b, c, d) {
  var e = a.memoizedProps;
  if (e !== d) {
    a = b.stateNode;
    xh(uh.current);
    var f2 = null;
    switch (c) {
      case "input":
        e = Ya(a, e);
        d = Ya(a, d);
        f2 = [];
        break;
      case "select":
        e = A({}, e, { value: void 0 });
        d = A({}, d, { value: void 0 });
        f2 = [];
        break;
      case "textarea":
        e = gb(a, e);
        d = gb(a, d);
        f2 = [];
        break;
      default:
        "function" !== typeof e.onClick && "function" === typeof d.onClick && (a.onclick = Bf);
    }
    ub(c, d);
    var g;
    c = null;
    for (l2 in e) if (!d.hasOwnProperty(l2) && e.hasOwnProperty(l2) && null != e[l2]) if ("style" === l2) {
      var h2 = e[l2];
      for (g in h2) h2.hasOwnProperty(g) && (c || (c = {}), c[g] = "");
    } else "dangerouslySetInnerHTML" !== l2 && "children" !== l2 && "suppressContentEditableWarning" !== l2 && "suppressHydrationWarning" !== l2 && "autoFocus" !== l2 && (ea.hasOwnProperty(l2) ? f2 || (f2 = []) : (f2 = f2 || []).push(l2, null));
    for (l2 in d) {
      var k2 = d[l2];
      h2 = null != e ? e[l2] : void 0;
      if (d.hasOwnProperty(l2) && k2 !== h2 && (null != k2 || null != h2)) if ("style" === l2) if (h2) {
        for (g in h2) !h2.hasOwnProperty(g) || k2 && k2.hasOwnProperty(g) || (c || (c = {}), c[g] = "");
        for (g in k2) k2.hasOwnProperty(g) && h2[g] !== k2[g] && (c || (c = {}), c[g] = k2[g]);
      } else c || (f2 || (f2 = []), f2.push(
        l2,
        c
      )), c = k2;
      else "dangerouslySetInnerHTML" === l2 ? (k2 = k2 ? k2.__html : void 0, h2 = h2 ? h2.__html : void 0, null != k2 && h2 !== k2 && (f2 = f2 || []).push(l2, k2)) : "children" === l2 ? "string" !== typeof k2 && "number" !== typeof k2 || (f2 = f2 || []).push(l2, "" + k2) : "suppressContentEditableWarning" !== l2 && "suppressHydrationWarning" !== l2 && (ea.hasOwnProperty(l2) ? (null != k2 && "onScroll" === l2 && D$1("scroll", a), f2 || h2 === k2 || (f2 = [])) : (f2 = f2 || []).push(l2, k2));
    }
    c && (f2 = f2 || []).push("style", c);
    var l2 = f2;
    if (b.updateQueue = l2) b.flags |= 4;
  }
};
Cj = function(a, b, c, d) {
  c !== d && (b.flags |= 4);
};
function Dj(a, b) {
  if (!I) switch (a.tailMode) {
    case "hidden":
      b = a.tail;
      for (var c = null; null !== b; ) null !== b.alternate && (c = b), b = b.sibling;
      null === c ? a.tail = null : c.sibling = null;
      break;
    case "collapsed":
      c = a.tail;
      for (var d = null; null !== c; ) null !== c.alternate && (d = c), c = c.sibling;
      null === d ? b || null === a.tail ? a.tail = null : a.tail.sibling = null : d.sibling = null;
  }
}
function S(a) {
  var b = null !== a.alternate && a.alternate.child === a.child, c = 0, d = 0;
  if (b) for (var e = a.child; null !== e; ) c |= e.lanes | e.childLanes, d |= e.subtreeFlags & 14680064, d |= e.flags & 14680064, e.return = a, e = e.sibling;
  else for (e = a.child; null !== e; ) c |= e.lanes | e.childLanes, d |= e.subtreeFlags, d |= e.flags, e.return = a, e = e.sibling;
  a.subtreeFlags |= d;
  a.childLanes = c;
  return b;
}
function Ej(a, b, c) {
  var d = b.pendingProps;
  wg(b);
  switch (b.tag) {
    case 2:
    case 16:
    case 15:
    case 0:
    case 11:
    case 7:
    case 8:
    case 12:
    case 9:
    case 14:
      return S(b), null;
    case 1:
      return Zf(b.type) && $f(), S(b), null;
    case 3:
      d = b.stateNode;
      zh();
      E(Wf);
      E(H$1);
      Eh();
      d.pendingContext && (d.context = d.pendingContext, d.pendingContext = null);
      if (null === a || null === a.child) Gg(b) ? b.flags |= 4 : null === a || a.memoizedState.isDehydrated && 0 === (b.flags & 256) || (b.flags |= 1024, null !== zg && (Fj(zg), zg = null));
      Aj(a, b);
      S(b);
      return null;
    case 5:
      Bh(b);
      var e = xh(wh.current);
      c = b.type;
      if (null !== a && null != b.stateNode) Bj(a, b, c, d, e), a.ref !== b.ref && (b.flags |= 512, b.flags |= 2097152);
      else {
        if (!d) {
          if (null === b.stateNode) throw Error(p(166));
          S(b);
          return null;
        }
        a = xh(uh.current);
        if (Gg(b)) {
          d = b.stateNode;
          c = b.type;
          var f2 = b.memoizedProps;
          d[Of] = b;
          d[Pf] = f2;
          a = 0 !== (b.mode & 1);
          switch (c) {
            case "dialog":
              D$1("cancel", d);
              D$1("close", d);
              break;
            case "iframe":
            case "object":
            case "embed":
              D$1("load", d);
              break;
            case "video":
            case "audio":
              for (e = 0; e < lf.length; e++) D$1(lf[e], d);
              break;
            case "source":
              D$1("error", d);
              break;
            case "img":
            case "image":
            case "link":
              D$1(
                "error",
                d
              );
              D$1("load", d);
              break;
            case "details":
              D$1("toggle", d);
              break;
            case "input":
              Za(d, f2);
              D$1("invalid", d);
              break;
            case "select":
              d._wrapperState = { wasMultiple: !!f2.multiple };
              D$1("invalid", d);
              break;
            case "textarea":
              hb(d, f2), D$1("invalid", d);
          }
          ub(c, f2);
          e = null;
          for (var g in f2) if (f2.hasOwnProperty(g)) {
            var h2 = f2[g];
            "children" === g ? "string" === typeof h2 ? d.textContent !== h2 && (true !== f2.suppressHydrationWarning && Af(d.textContent, h2, a), e = ["children", h2]) : "number" === typeof h2 && d.textContent !== "" + h2 && (true !== f2.suppressHydrationWarning && Af(
              d.textContent,
              h2,
              a
            ), e = ["children", "" + h2]) : ea.hasOwnProperty(g) && null != h2 && "onScroll" === g && D$1("scroll", d);
          }
          switch (c) {
            case "input":
              Va(d);
              db(d, f2, true);
              break;
            case "textarea":
              Va(d);
              jb(d);
              break;
            case "select":
            case "option":
              break;
            default:
              "function" === typeof f2.onClick && (d.onclick = Bf);
          }
          d = e;
          b.updateQueue = d;
          null !== d && (b.flags |= 4);
        } else {
          g = 9 === e.nodeType ? e : e.ownerDocument;
          "http://www.w3.org/1999/xhtml" === a && (a = kb(c));
          "http://www.w3.org/1999/xhtml" === a ? "script" === c ? (a = g.createElement("div"), a.innerHTML = "<script><\/script>", a = a.removeChild(a.firstChild)) : "string" === typeof d.is ? a = g.createElement(c, { is: d.is }) : (a = g.createElement(c), "select" === c && (g = a, d.multiple ? g.multiple = true : d.size && (g.size = d.size))) : a = g.createElementNS(a, c);
          a[Of] = b;
          a[Pf] = d;
          zj(a, b, false, false);
          b.stateNode = a;
          a: {
            g = vb(c, d);
            switch (c) {
              case "dialog":
                D$1("cancel", a);
                D$1("close", a);
                e = d;
                break;
              case "iframe":
              case "object":
              case "embed":
                D$1("load", a);
                e = d;
                break;
              case "video":
              case "audio":
                for (e = 0; e < lf.length; e++) D$1(lf[e], a);
                e = d;
                break;
              case "source":
                D$1("error", a);
                e = d;
                break;
              case "img":
              case "image":
              case "link":
                D$1(
                  "error",
                  a
                );
                D$1("load", a);
                e = d;
                break;
              case "details":
                D$1("toggle", a);
                e = d;
                break;
              case "input":
                Za(a, d);
                e = Ya(a, d);
                D$1("invalid", a);
                break;
              case "option":
                e = d;
                break;
              case "select":
                a._wrapperState = { wasMultiple: !!d.multiple };
                e = A({}, d, { value: void 0 });
                D$1("invalid", a);
                break;
              case "textarea":
                hb(a, d);
                e = gb(a, d);
                D$1("invalid", a);
                break;
              default:
                e = d;
            }
            ub(c, e);
            h2 = e;
            for (f2 in h2) if (h2.hasOwnProperty(f2)) {
              var k2 = h2[f2];
              "style" === f2 ? sb(a, k2) : "dangerouslySetInnerHTML" === f2 ? (k2 = k2 ? k2.__html : void 0, null != k2 && nb(a, k2)) : "children" === f2 ? "string" === typeof k2 ? ("textarea" !== c || "" !== k2) && ob(a, k2) : "number" === typeof k2 && ob(a, "" + k2) : "suppressContentEditableWarning" !== f2 && "suppressHydrationWarning" !== f2 && "autoFocus" !== f2 && (ea.hasOwnProperty(f2) ? null != k2 && "onScroll" === f2 && D$1("scroll", a) : null != k2 && ta(a, f2, k2, g));
            }
            switch (c) {
              case "input":
                Va(a);
                db(a, d, false);
                break;
              case "textarea":
                Va(a);
                jb(a);
                break;
              case "option":
                null != d.value && a.setAttribute("value", "" + Sa(d.value));
                break;
              case "select":
                a.multiple = !!d.multiple;
                f2 = d.value;
                null != f2 ? fb(a, !!d.multiple, f2, false) : null != d.defaultValue && fb(
                  a,
                  !!d.multiple,
                  d.defaultValue,
                  true
                );
                break;
              default:
                "function" === typeof e.onClick && (a.onclick = Bf);
            }
            switch (c) {
              case "button":
              case "input":
              case "select":
              case "textarea":
                d = !!d.autoFocus;
                break a;
              case "img":
                d = true;
                break a;
              default:
                d = false;
            }
          }
          d && (b.flags |= 4);
        }
        null !== b.ref && (b.flags |= 512, b.flags |= 2097152);
      }
      S(b);
      return null;
    case 6:
      if (a && null != b.stateNode) Cj(a, b, a.memoizedProps, d);
      else {
        if ("string" !== typeof d && null === b.stateNode) throw Error(p(166));
        c = xh(wh.current);
        xh(uh.current);
        if (Gg(b)) {
          d = b.stateNode;
          c = b.memoizedProps;
          d[Of] = b;
          if (f2 = d.nodeValue !== c) {
            if (a = xg, null !== a) switch (a.tag) {
              case 3:
                Af(d.nodeValue, c, 0 !== (a.mode & 1));
                break;
              case 5:
                true !== a.memoizedProps.suppressHydrationWarning && Af(d.nodeValue, c, 0 !== (a.mode & 1));
            }
          }
          f2 && (b.flags |= 4);
        } else d = (9 === c.nodeType ? c : c.ownerDocument).createTextNode(d), d[Of] = b, b.stateNode = d;
      }
      S(b);
      return null;
    case 13:
      E(L);
      d = b.memoizedState;
      if (null === a || null !== a.memoizedState && null !== a.memoizedState.dehydrated) {
        if (I && null !== yg && 0 !== (b.mode & 1) && 0 === (b.flags & 128)) Hg(), Ig(), b.flags |= 98560, f2 = false;
        else if (f2 = Gg(b), null !== d && null !== d.dehydrated) {
          if (null === a) {
            if (!f2) throw Error(p(318));
            f2 = b.memoizedState;
            f2 = null !== f2 ? f2.dehydrated : null;
            if (!f2) throw Error(p(317));
            f2[Of] = b;
          } else Ig(), 0 === (b.flags & 128) && (b.memoizedState = null), b.flags |= 4;
          S(b);
          f2 = false;
        } else null !== zg && (Fj(zg), zg = null), f2 = true;
        if (!f2) return b.flags & 65536 ? b : null;
      }
      if (0 !== (b.flags & 128)) return b.lanes = c, b;
      d = null !== d;
      d !== (null !== a && null !== a.memoizedState) && d && (b.child.flags |= 8192, 0 !== (b.mode & 1) && (null === a || 0 !== (L.current & 1) ? 0 === T && (T = 3) : tj()));
      null !== b.updateQueue && (b.flags |= 4);
      S(b);
      return null;
    case 4:
      return zh(), Aj(a, b), null === a && sf(b.stateNode.containerInfo), S(b), null;
    case 10:
      return ah(b.type._context), S(b), null;
    case 17:
      return Zf(b.type) && $f(), S(b), null;
    case 19:
      E(L);
      f2 = b.memoizedState;
      if (null === f2) return S(b), null;
      d = 0 !== (b.flags & 128);
      g = f2.rendering;
      if (null === g) if (d) Dj(f2, false);
      else {
        if (0 !== T || null !== a && 0 !== (a.flags & 128)) for (a = b.child; null !== a; ) {
          g = Ch(a);
          if (null !== g) {
            b.flags |= 128;
            Dj(f2, false);
            d = g.updateQueue;
            null !== d && (b.updateQueue = d, b.flags |= 4);
            b.subtreeFlags = 0;
            d = c;
            for (c = b.child; null !== c; ) f2 = c, a = d, f2.flags &= 14680066, g = f2.alternate, null === g ? (f2.childLanes = 0, f2.lanes = a, f2.child = null, f2.subtreeFlags = 0, f2.memoizedProps = null, f2.memoizedState = null, f2.updateQueue = null, f2.dependencies = null, f2.stateNode = null) : (f2.childLanes = g.childLanes, f2.lanes = g.lanes, f2.child = g.child, f2.subtreeFlags = 0, f2.deletions = null, f2.memoizedProps = g.memoizedProps, f2.memoizedState = g.memoizedState, f2.updateQueue = g.updateQueue, f2.type = g.type, a = g.dependencies, f2.dependencies = null === a ? null : { lanes: a.lanes, firstContext: a.firstContext }), c = c.sibling;
            G(L, L.current & 1 | 2);
            return b.child;
          }
          a = a.sibling;
        }
        null !== f2.tail && B() > Gj && (b.flags |= 128, d = true, Dj(f2, false), b.lanes = 4194304);
      }
      else {
        if (!d) if (a = Ch(g), null !== a) {
          if (b.flags |= 128, d = true, c = a.updateQueue, null !== c && (b.updateQueue = c, b.flags |= 4), Dj(f2, true), null === f2.tail && "hidden" === f2.tailMode && !g.alternate && !I) return S(b), null;
        } else 2 * B() - f2.renderingStartTime > Gj && 1073741824 !== c && (b.flags |= 128, d = true, Dj(f2, false), b.lanes = 4194304);
        f2.isBackwards ? (g.sibling = b.child, b.child = g) : (c = f2.last, null !== c ? c.sibling = g : b.child = g, f2.last = g);
      }
      if (null !== f2.tail) return b = f2.tail, f2.rendering = b, f2.tail = b.sibling, f2.renderingStartTime = B(), b.sibling = null, c = L.current, G(L, d ? c & 1 | 2 : c & 1), b;
      S(b);
      return null;
    case 22:
    case 23:
      return Hj(), d = null !== b.memoizedState, null !== a && null !== a.memoizedState !== d && (b.flags |= 8192), d && 0 !== (b.mode & 1) ? 0 !== (fj & 1073741824) && (S(b), b.subtreeFlags & 6 && (b.flags |= 8192)) : S(b), null;
    case 24:
      return null;
    case 25:
      return null;
  }
  throw Error(p(156, b.tag));
}
function Ij(a, b) {
  wg(b);
  switch (b.tag) {
    case 1:
      return Zf(b.type) && $f(), a = b.flags, a & 65536 ? (b.flags = a & -65537 | 128, b) : null;
    case 3:
      return zh(), E(Wf), E(H$1), Eh(), a = b.flags, 0 !== (a & 65536) && 0 === (a & 128) ? (b.flags = a & -65537 | 128, b) : null;
    case 5:
      return Bh(b), null;
    case 13:
      E(L);
      a = b.memoizedState;
      if (null !== a && null !== a.dehydrated) {
        if (null === b.alternate) throw Error(p(340));
        Ig();
      }
      a = b.flags;
      return a & 65536 ? (b.flags = a & -65537 | 128, b) : null;
    case 19:
      return E(L), null;
    case 4:
      return zh(), null;
    case 10:
      return ah(b.type._context), null;
    case 22:
    case 23:
      return Hj(), null;
    case 24:
      return null;
    default:
      return null;
  }
}
var Jj = false, U = false, Kj = "function" === typeof WeakSet ? WeakSet : Set, V = null;
function Lj(a, b) {
  var c = a.ref;
  if (null !== c) if ("function" === typeof c) try {
    c(null);
  } catch (d) {
    W(a, b, d);
  }
  else c.current = null;
}
function Mj(a, b, c) {
  try {
    c();
  } catch (d) {
    W(a, b, d);
  }
}
var Nj = false;
function Oj(a, b) {
  Cf = dd;
  a = Me$1();
  if (Ne(a)) {
    if ("selectionStart" in a) var c = { start: a.selectionStart, end: a.selectionEnd };
    else a: {
      c = (c = a.ownerDocument) && c.defaultView || window;
      var d = c.getSelection && c.getSelection();
      if (d && 0 !== d.rangeCount) {
        c = d.anchorNode;
        var e = d.anchorOffset, f2 = d.focusNode;
        d = d.focusOffset;
        try {
          c.nodeType, f2.nodeType;
        } catch (F2) {
          c = null;
          break a;
        }
        var g = 0, h2 = -1, k2 = -1, l2 = 0, m2 = 0, q2 = a, r2 = null;
        b: for (; ; ) {
          for (var y2; ; ) {
            q2 !== c || 0 !== e && 3 !== q2.nodeType || (h2 = g + e);
            q2 !== f2 || 0 !== d && 3 !== q2.nodeType || (k2 = g + d);
            3 === q2.nodeType && (g += q2.nodeValue.length);
            if (null === (y2 = q2.firstChild)) break;
            r2 = q2;
            q2 = y2;
          }
          for (; ; ) {
            if (q2 === a) break b;
            r2 === c && ++l2 === e && (h2 = g);
            r2 === f2 && ++m2 === d && (k2 = g);
            if (null !== (y2 = q2.nextSibling)) break;
            q2 = r2;
            r2 = q2.parentNode;
          }
          q2 = y2;
        }
        c = -1 === h2 || -1 === k2 ? null : { start: h2, end: k2 };
      } else c = null;
    }
    c = c || { start: 0, end: 0 };
  } else c = null;
  Df = { focusedElem: a, selectionRange: c };
  dd = false;
  for (V = b; null !== V; ) if (b = V, a = b.child, 0 !== (b.subtreeFlags & 1028) && null !== a) a.return = b, V = a;
  else for (; null !== V; ) {
    b = V;
    try {
      var n2 = b.alternate;
      if (0 !== (b.flags & 1024)) switch (b.tag) {
        case 0:
        case 11:
        case 15:
          break;
        case 1:
          if (null !== n2) {
            var t2 = n2.memoizedProps, J2 = n2.memoizedState, x2 = b.stateNode, w2 = x2.getSnapshotBeforeUpdate(b.elementType === b.type ? t2 : Ci(b.type, t2), J2);
            x2.__reactInternalSnapshotBeforeUpdate = w2;
          }
          break;
        case 3:
          var u2 = b.stateNode.containerInfo;
          1 === u2.nodeType ? u2.textContent = "" : 9 === u2.nodeType && u2.documentElement && u2.removeChild(u2.documentElement);
          break;
        case 5:
        case 6:
        case 4:
        case 17:
          break;
        default:
          throw Error(p(163));
      }
    } catch (F2) {
      W(b, b.return, F2);
    }
    a = b.sibling;
    if (null !== a) {
      a.return = b.return;
      V = a;
      break;
    }
    V = b.return;
  }
  n2 = Nj;
  Nj = false;
  return n2;
}
function Pj(a, b, c) {
  var d = b.updateQueue;
  d = null !== d ? d.lastEffect : null;
  if (null !== d) {
    var e = d = d.next;
    do {
      if ((e.tag & a) === a) {
        var f2 = e.destroy;
        e.destroy = void 0;
        void 0 !== f2 && Mj(b, c, f2);
      }
      e = e.next;
    } while (e !== d);
  }
}
function Qj(a, b) {
  b = b.updateQueue;
  b = null !== b ? b.lastEffect : null;
  if (null !== b) {
    var c = b = b.next;
    do {
      if ((c.tag & a) === a) {
        var d = c.create;
        c.destroy = d();
      }
      c = c.next;
    } while (c !== b);
  }
}
function Rj(a) {
  var b = a.ref;
  if (null !== b) {
    var c = a.stateNode;
    switch (a.tag) {
      case 5:
        a = c;
        break;
      default:
        a = c;
    }
    "function" === typeof b ? b(a) : b.current = a;
  }
}
function Sj(a) {
  var b = a.alternate;
  null !== b && (a.alternate = null, Sj(b));
  a.child = null;
  a.deletions = null;
  a.sibling = null;
  5 === a.tag && (b = a.stateNode, null !== b && (delete b[Of], delete b[Pf], delete b[of], delete b[Qf], delete b[Rf]));
  a.stateNode = null;
  a.return = null;
  a.dependencies = null;
  a.memoizedProps = null;
  a.memoizedState = null;
  a.pendingProps = null;
  a.stateNode = null;
  a.updateQueue = null;
}
function Tj(a) {
  return 5 === a.tag || 3 === a.tag || 4 === a.tag;
}
function Uj(a) {
  a: for (; ; ) {
    for (; null === a.sibling; ) {
      if (null === a.return || Tj(a.return)) return null;
      a = a.return;
    }
    a.sibling.return = a.return;
    for (a = a.sibling; 5 !== a.tag && 6 !== a.tag && 18 !== a.tag; ) {
      if (a.flags & 2) continue a;
      if (null === a.child || 4 === a.tag) continue a;
      else a.child.return = a, a = a.child;
    }
    if (!(a.flags & 2)) return a.stateNode;
  }
}
function Vj(a, b, c) {
  var d = a.tag;
  if (5 === d || 6 === d) a = a.stateNode, b ? 8 === c.nodeType ? c.parentNode.insertBefore(a, b) : c.insertBefore(a, b) : (8 === c.nodeType ? (b = c.parentNode, b.insertBefore(a, c)) : (b = c, b.appendChild(a)), c = c._reactRootContainer, null !== c && void 0 !== c || null !== b.onclick || (b.onclick = Bf));
  else if (4 !== d && (a = a.child, null !== a)) for (Vj(a, b, c), a = a.sibling; null !== a; ) Vj(a, b, c), a = a.sibling;
}
function Wj(a, b, c) {
  var d = a.tag;
  if (5 === d || 6 === d) a = a.stateNode, b ? c.insertBefore(a, b) : c.appendChild(a);
  else if (4 !== d && (a = a.child, null !== a)) for (Wj(a, b, c), a = a.sibling; null !== a; ) Wj(a, b, c), a = a.sibling;
}
var X = null, Xj = false;
function Yj(a, b, c) {
  for (c = c.child; null !== c; ) Zj(a, b, c), c = c.sibling;
}
function Zj(a, b, c) {
  if (lc && "function" === typeof lc.onCommitFiberUnmount) try {
    lc.onCommitFiberUnmount(kc, c);
  } catch (h2) {
  }
  switch (c.tag) {
    case 5:
      U || Lj(c, b);
    case 6:
      var d = X, e = Xj;
      X = null;
      Yj(a, b, c);
      X = d;
      Xj = e;
      null !== X && (Xj ? (a = X, c = c.stateNode, 8 === a.nodeType ? a.parentNode.removeChild(c) : a.removeChild(c)) : X.removeChild(c.stateNode));
      break;
    case 18:
      null !== X && (Xj ? (a = X, c = c.stateNode, 8 === a.nodeType ? Kf(a.parentNode, c) : 1 === a.nodeType && Kf(a, c), bd(a)) : Kf(X, c.stateNode));
      break;
    case 4:
      d = X;
      e = Xj;
      X = c.stateNode.containerInfo;
      Xj = true;
      Yj(a, b, c);
      X = d;
      Xj = e;
      break;
    case 0:
    case 11:
    case 14:
    case 15:
      if (!U && (d = c.updateQueue, null !== d && (d = d.lastEffect, null !== d))) {
        e = d = d.next;
        do {
          var f2 = e, g = f2.destroy;
          f2 = f2.tag;
          void 0 !== g && (0 !== (f2 & 2) ? Mj(c, b, g) : 0 !== (f2 & 4) && Mj(c, b, g));
          e = e.next;
        } while (e !== d);
      }
      Yj(a, b, c);
      break;
    case 1:
      if (!U && (Lj(c, b), d = c.stateNode, "function" === typeof d.componentWillUnmount)) try {
        d.props = c.memoizedProps, d.state = c.memoizedState, d.componentWillUnmount();
      } catch (h2) {
        W(c, b, h2);
      }
      Yj(a, b, c);
      break;
    case 21:
      Yj(a, b, c);
      break;
    case 22:
      c.mode & 1 ? (U = (d = U) || null !== c.memoizedState, Yj(a, b, c), U = d) : Yj(a, b, c);
      break;
    default:
      Yj(a, b, c);
  }
}
function ak(a) {
  var b = a.updateQueue;
  if (null !== b) {
    a.updateQueue = null;
    var c = a.stateNode;
    null === c && (c = a.stateNode = new Kj());
    b.forEach(function(b2) {
      var d = bk.bind(null, a, b2);
      c.has(b2) || (c.add(b2), b2.then(d, d));
    });
  }
}
function ck(a, b) {
  var c = b.deletions;
  if (null !== c) for (var d = 0; d < c.length; d++) {
    var e = c[d];
    try {
      var f2 = a, g = b, h2 = g;
      a: for (; null !== h2; ) {
        switch (h2.tag) {
          case 5:
            X = h2.stateNode;
            Xj = false;
            break a;
          case 3:
            X = h2.stateNode.containerInfo;
            Xj = true;
            break a;
          case 4:
            X = h2.stateNode.containerInfo;
            Xj = true;
            break a;
        }
        h2 = h2.return;
      }
      if (null === X) throw Error(p(160));
      Zj(f2, g, e);
      X = null;
      Xj = false;
      var k2 = e.alternate;
      null !== k2 && (k2.return = null);
      e.return = null;
    } catch (l2) {
      W(e, b, l2);
    }
  }
  if (b.subtreeFlags & 12854) for (b = b.child; null !== b; ) dk(b, a), b = b.sibling;
}
function dk(a, b) {
  var c = a.alternate, d = a.flags;
  switch (a.tag) {
    case 0:
    case 11:
    case 14:
    case 15:
      ck(b, a);
      ek(a);
      if (d & 4) {
        try {
          Pj(3, a, a.return), Qj(3, a);
        } catch (t2) {
          W(a, a.return, t2);
        }
        try {
          Pj(5, a, a.return);
        } catch (t2) {
          W(a, a.return, t2);
        }
      }
      break;
    case 1:
      ck(b, a);
      ek(a);
      d & 512 && null !== c && Lj(c, c.return);
      break;
    case 5:
      ck(b, a);
      ek(a);
      d & 512 && null !== c && Lj(c, c.return);
      if (a.flags & 32) {
        var e = a.stateNode;
        try {
          ob(e, "");
        } catch (t2) {
          W(a, a.return, t2);
        }
      }
      if (d & 4 && (e = a.stateNode, null != e)) {
        var f2 = a.memoizedProps, g = null !== c ? c.memoizedProps : f2, h2 = a.type, k2 = a.updateQueue;
        a.updateQueue = null;
        if (null !== k2) try {
          "input" === h2 && "radio" === f2.type && null != f2.name && ab(e, f2);
          vb(h2, g);
          var l2 = vb(h2, f2);
          for (g = 0; g < k2.length; g += 2) {
            var m2 = k2[g], q2 = k2[g + 1];
            "style" === m2 ? sb(e, q2) : "dangerouslySetInnerHTML" === m2 ? nb(e, q2) : "children" === m2 ? ob(e, q2) : ta(e, m2, q2, l2);
          }
          switch (h2) {
            case "input":
              bb(e, f2);
              break;
            case "textarea":
              ib(e, f2);
              break;
            case "select":
              var r2 = e._wrapperState.wasMultiple;
              e._wrapperState.wasMultiple = !!f2.multiple;
              var y2 = f2.value;
              null != y2 ? fb(e, !!f2.multiple, y2, false) : r2 !== !!f2.multiple && (null != f2.defaultValue ? fb(
                e,
                !!f2.multiple,
                f2.defaultValue,
                true
              ) : fb(e, !!f2.multiple, f2.multiple ? [] : "", false));
          }
          e[Pf] = f2;
        } catch (t2) {
          W(a, a.return, t2);
        }
      }
      break;
    case 6:
      ck(b, a);
      ek(a);
      if (d & 4) {
        if (null === a.stateNode) throw Error(p(162));
        e = a.stateNode;
        f2 = a.memoizedProps;
        try {
          e.nodeValue = f2;
        } catch (t2) {
          W(a, a.return, t2);
        }
      }
      break;
    case 3:
      ck(b, a);
      ek(a);
      if (d & 4 && null !== c && c.memoizedState.isDehydrated) try {
        bd(b.containerInfo);
      } catch (t2) {
        W(a, a.return, t2);
      }
      break;
    case 4:
      ck(b, a);
      ek(a);
      break;
    case 13:
      ck(b, a);
      ek(a);
      e = a.child;
      e.flags & 8192 && (f2 = null !== e.memoizedState, e.stateNode.isHidden = f2, !f2 || null !== e.alternate && null !== e.alternate.memoizedState || (fk = B()));
      d & 4 && ak(a);
      break;
    case 22:
      m2 = null !== c && null !== c.memoizedState;
      a.mode & 1 ? (U = (l2 = U) || m2, ck(b, a), U = l2) : ck(b, a);
      ek(a);
      if (d & 8192) {
        l2 = null !== a.memoizedState;
        if ((a.stateNode.isHidden = l2) && !m2 && 0 !== (a.mode & 1)) for (V = a, m2 = a.child; null !== m2; ) {
          for (q2 = V = m2; null !== V; ) {
            r2 = V;
            y2 = r2.child;
            switch (r2.tag) {
              case 0:
              case 11:
              case 14:
              case 15:
                Pj(4, r2, r2.return);
                break;
              case 1:
                Lj(r2, r2.return);
                var n2 = r2.stateNode;
                if ("function" === typeof n2.componentWillUnmount) {
                  d = r2;
                  c = r2.return;
                  try {
                    b = d, n2.props = b.memoizedProps, n2.state = b.memoizedState, n2.componentWillUnmount();
                  } catch (t2) {
                    W(d, c, t2);
                  }
                }
                break;
              case 5:
                Lj(r2, r2.return);
                break;
              case 22:
                if (null !== r2.memoizedState) {
                  gk(q2);
                  continue;
                }
            }
            null !== y2 ? (y2.return = r2, V = y2) : gk(q2);
          }
          m2 = m2.sibling;
        }
        a: for (m2 = null, q2 = a; ; ) {
          if (5 === q2.tag) {
            if (null === m2) {
              m2 = q2;
              try {
                e = q2.stateNode, l2 ? (f2 = e.style, "function" === typeof f2.setProperty ? f2.setProperty("display", "none", "important") : f2.display = "none") : (h2 = q2.stateNode, k2 = q2.memoizedProps.style, g = void 0 !== k2 && null !== k2 && k2.hasOwnProperty("display") ? k2.display : null, h2.style.display = rb("display", g));
              } catch (t2) {
                W(a, a.return, t2);
              }
            }
          } else if (6 === q2.tag) {
            if (null === m2) try {
              q2.stateNode.nodeValue = l2 ? "" : q2.memoizedProps;
            } catch (t2) {
              W(a, a.return, t2);
            }
          } else if ((22 !== q2.tag && 23 !== q2.tag || null === q2.memoizedState || q2 === a) && null !== q2.child) {
            q2.child.return = q2;
            q2 = q2.child;
            continue;
          }
          if (q2 === a) break a;
          for (; null === q2.sibling; ) {
            if (null === q2.return || q2.return === a) break a;
            m2 === q2 && (m2 = null);
            q2 = q2.return;
          }
          m2 === q2 && (m2 = null);
          q2.sibling.return = q2.return;
          q2 = q2.sibling;
        }
      }
      break;
    case 19:
      ck(b, a);
      ek(a);
      d & 4 && ak(a);
      break;
    case 21:
      break;
    default:
      ck(
        b,
        a
      ), ek(a);
  }
}
function ek(a) {
  var b = a.flags;
  if (b & 2) {
    try {
      a: {
        for (var c = a.return; null !== c; ) {
          if (Tj(c)) {
            var d = c;
            break a;
          }
          c = c.return;
        }
        throw Error(p(160));
      }
      switch (d.tag) {
        case 5:
          var e = d.stateNode;
          d.flags & 32 && (ob(e, ""), d.flags &= -33);
          var f2 = Uj(a);
          Wj(a, f2, e);
          break;
        case 3:
        case 4:
          var g = d.stateNode.containerInfo, h2 = Uj(a);
          Vj(a, h2, g);
          break;
        default:
          throw Error(p(161));
      }
    } catch (k2) {
      W(a, a.return, k2);
    }
    a.flags &= -3;
  }
  b & 4096 && (a.flags &= -4097);
}
function hk(a, b, c) {
  V = a;
  ik(a);
}
function ik(a, b, c) {
  for (var d = 0 !== (a.mode & 1); null !== V; ) {
    var e = V, f2 = e.child;
    if (22 === e.tag && d) {
      var g = null !== e.memoizedState || Jj;
      if (!g) {
        var h2 = e.alternate, k2 = null !== h2 && null !== h2.memoizedState || U;
        h2 = Jj;
        var l2 = U;
        Jj = g;
        if ((U = k2) && !l2) for (V = e; null !== V; ) g = V, k2 = g.child, 22 === g.tag && null !== g.memoizedState ? jk(e) : null !== k2 ? (k2.return = g, V = k2) : jk(e);
        for (; null !== f2; ) V = f2, ik(f2), f2 = f2.sibling;
        V = e;
        Jj = h2;
        U = l2;
      }
      kk(a);
    } else 0 !== (e.subtreeFlags & 8772) && null !== f2 ? (f2.return = e, V = f2) : kk(a);
  }
}
function kk(a) {
  for (; null !== V; ) {
    var b = V;
    if (0 !== (b.flags & 8772)) {
      var c = b.alternate;
      try {
        if (0 !== (b.flags & 8772)) switch (b.tag) {
          case 0:
          case 11:
          case 15:
            U || Qj(5, b);
            break;
          case 1:
            var d = b.stateNode;
            if (b.flags & 4 && !U) if (null === c) d.componentDidMount();
            else {
              var e = b.elementType === b.type ? c.memoizedProps : Ci(b.type, c.memoizedProps);
              d.componentDidUpdate(e, c.memoizedState, d.__reactInternalSnapshotBeforeUpdate);
            }
            var f2 = b.updateQueue;
            null !== f2 && sh(b, f2, d);
            break;
          case 3:
            var g = b.updateQueue;
            if (null !== g) {
              c = null;
              if (null !== b.child) switch (b.child.tag) {
                case 5:
                  c = b.child.stateNode;
                  break;
                case 1:
                  c = b.child.stateNode;
              }
              sh(b, g, c);
            }
            break;
          case 5:
            var h2 = b.stateNode;
            if (null === c && b.flags & 4) {
              c = h2;
              var k2 = b.memoizedProps;
              switch (b.type) {
                case "button":
                case "input":
                case "select":
                case "textarea":
                  k2.autoFocus && c.focus();
                  break;
                case "img":
                  k2.src && (c.src = k2.src);
              }
            }
            break;
          case 6:
            break;
          case 4:
            break;
          case 12:
            break;
          case 13:
            if (null === b.memoizedState) {
              var l2 = b.alternate;
              if (null !== l2) {
                var m2 = l2.memoizedState;
                if (null !== m2) {
                  var q2 = m2.dehydrated;
                  null !== q2 && bd(q2);
                }
              }
            }
            break;
          case 19:
          case 17:
          case 21:
          case 22:
          case 23:
          case 25:
            break;
          default:
            throw Error(p(163));
        }
        U || b.flags & 512 && Rj(b);
      } catch (r2) {
        W(b, b.return, r2);
      }
    }
    if (b === a) {
      V = null;
      break;
    }
    c = b.sibling;
    if (null !== c) {
      c.return = b.return;
      V = c;
      break;
    }
    V = b.return;
  }
}
function gk(a) {
  for (; null !== V; ) {
    var b = V;
    if (b === a) {
      V = null;
      break;
    }
    var c = b.sibling;
    if (null !== c) {
      c.return = b.return;
      V = c;
      break;
    }
    V = b.return;
  }
}
function jk(a) {
  for (; null !== V; ) {
    var b = V;
    try {
      switch (b.tag) {
        case 0:
        case 11:
        case 15:
          var c = b.return;
          try {
            Qj(4, b);
          } catch (k2) {
            W(b, c, k2);
          }
          break;
        case 1:
          var d = b.stateNode;
          if ("function" === typeof d.componentDidMount) {
            var e = b.return;
            try {
              d.componentDidMount();
            } catch (k2) {
              W(b, e, k2);
            }
          }
          var f2 = b.return;
          try {
            Rj(b);
          } catch (k2) {
            W(b, f2, k2);
          }
          break;
        case 5:
          var g = b.return;
          try {
            Rj(b);
          } catch (k2) {
            W(b, g, k2);
          }
      }
    } catch (k2) {
      W(b, b.return, k2);
    }
    if (b === a) {
      V = null;
      break;
    }
    var h2 = b.sibling;
    if (null !== h2) {
      h2.return = b.return;
      V = h2;
      break;
    }
    V = b.return;
  }
}
var lk = Math.ceil, mk = ua.ReactCurrentDispatcher, nk = ua.ReactCurrentOwner, ok = ua.ReactCurrentBatchConfig, K = 0, Q = null, Y$1 = null, Z$1 = 0, fj = 0, ej = Uf(0), T = 0, pk = null, rh = 0, qk = 0, rk = 0, sk = null, tk = null, fk = 0, Gj = Infinity, uk = null, Oi = false, Pi = null, Ri = null, vk = false, wk = null, xk = 0, yk = 0, zk = null, Ak = -1, Bk = 0;
function R() {
  return 0 !== (K & 6) ? B() : -1 !== Ak ? Ak : Ak = B();
}
function yi(a) {
  if (0 === (a.mode & 1)) return 1;
  if (0 !== (K & 2) && 0 !== Z$1) return Z$1 & -Z$1;
  if (null !== Kg.transition) return 0 === Bk && (Bk = yc()), Bk;
  a = C;
  if (0 !== a) return a;
  a = window.event;
  a = void 0 === a ? 16 : jd(a.type);
  return a;
}
function gi(a, b, c, d) {
  if (50 < yk) throw yk = 0, zk = null, Error(p(185));
  Ac(a, c, d);
  if (0 === (K & 2) || a !== Q) a === Q && (0 === (K & 2) && (qk |= c), 4 === T && Ck(a, Z$1)), Dk(a, d), 1 === c && 0 === K && 0 === (b.mode & 1) && (Gj = B() + 500, fg && jg());
}
function Dk(a, b) {
  var c = a.callbackNode;
  wc(a, b);
  var d = uc(a, a === Q ? Z$1 : 0);
  if (0 === d) null !== c && bc(c), a.callbackNode = null, a.callbackPriority = 0;
  else if (b = d & -d, a.callbackPriority !== b) {
    null != c && bc(c);
    if (1 === b) 0 === a.tag ? ig(Ek.bind(null, a)) : hg(Ek.bind(null, a)), Jf(function() {
      0 === (K & 6) && jg();
    }), c = null;
    else {
      switch (Dc(d)) {
        case 1:
          c = fc;
          break;
        case 4:
          c = gc;
          break;
        case 16:
          c = hc;
          break;
        case 536870912:
          c = jc;
          break;
        default:
          c = hc;
      }
      c = Fk(c, Gk.bind(null, a));
    }
    a.callbackPriority = b;
    a.callbackNode = c;
  }
}
function Gk(a, b) {
  Ak = -1;
  Bk = 0;
  if (0 !== (K & 6)) throw Error(p(327));
  var c = a.callbackNode;
  if (Hk() && a.callbackNode !== c) return null;
  var d = uc(a, a === Q ? Z$1 : 0);
  if (0 === d) return null;
  if (0 !== (d & 30) || 0 !== (d & a.expiredLanes) || b) b = Ik(a, d);
  else {
    b = d;
    var e = K;
    K |= 2;
    var f2 = Jk();
    if (Q !== a || Z$1 !== b) uk = null, Gj = B() + 500, Kk(a, b);
    do
      try {
        Lk();
        break;
      } catch (h2) {
        Mk(a, h2);
      }
    while (1);
    $g();
    mk.current = f2;
    K = e;
    null !== Y$1 ? b = 0 : (Q = null, Z$1 = 0, b = T);
  }
  if (0 !== b) {
    2 === b && (e = xc(a), 0 !== e && (d = e, b = Nk(a, e)));
    if (1 === b) throw c = pk, Kk(a, 0), Ck(a, d), Dk(a, B()), c;
    if (6 === b) Ck(a, d);
    else {
      e = a.current.alternate;
      if (0 === (d & 30) && !Ok(e) && (b = Ik(a, d), 2 === b && (f2 = xc(a), 0 !== f2 && (d = f2, b = Nk(a, f2))), 1 === b)) throw c = pk, Kk(a, 0), Ck(a, d), Dk(a, B()), c;
      a.finishedWork = e;
      a.finishedLanes = d;
      switch (b) {
        case 0:
        case 1:
          throw Error(p(345));
        case 2:
          Pk(a, tk, uk);
          break;
        case 3:
          Ck(a, d);
          if ((d & 130023424) === d && (b = fk + 500 - B(), 10 < b)) {
            if (0 !== uc(a, 0)) break;
            e = a.suspendedLanes;
            if ((e & d) !== d) {
              R();
              a.pingedLanes |= a.suspendedLanes & e;
              break;
            }
            a.timeoutHandle = Ff(Pk.bind(null, a, tk, uk), b);
            break;
          }
          Pk(a, tk, uk);
          break;
        case 4:
          Ck(a, d);
          if ((d & 4194240) === d) break;
          b = a.eventTimes;
          for (e = -1; 0 < d; ) {
            var g = 31 - oc(d);
            f2 = 1 << g;
            g = b[g];
            g > e && (e = g);
            d &= ~f2;
          }
          d = e;
          d = B() - d;
          d = (120 > d ? 120 : 480 > d ? 480 : 1080 > d ? 1080 : 1920 > d ? 1920 : 3e3 > d ? 3e3 : 4320 > d ? 4320 : 1960 * lk(d / 1960)) - d;
          if (10 < d) {
            a.timeoutHandle = Ff(Pk.bind(null, a, tk, uk), d);
            break;
          }
          Pk(a, tk, uk);
          break;
        case 5:
          Pk(a, tk, uk);
          break;
        default:
          throw Error(p(329));
      }
    }
  }
  Dk(a, B());
  return a.callbackNode === c ? Gk.bind(null, a) : null;
}
function Nk(a, b) {
  var c = sk;
  a.current.memoizedState.isDehydrated && (Kk(a, b).flags |= 256);
  a = Ik(a, b);
  2 !== a && (b = tk, tk = c, null !== b && Fj(b));
  return a;
}
function Fj(a) {
  null === tk ? tk = a : tk.push.apply(tk, a);
}
function Ok(a) {
  for (var b = a; ; ) {
    if (b.flags & 16384) {
      var c = b.updateQueue;
      if (null !== c && (c = c.stores, null !== c)) for (var d = 0; d < c.length; d++) {
        var e = c[d], f2 = e.getSnapshot;
        e = e.value;
        try {
          if (!He$1(f2(), e)) return false;
        } catch (g) {
          return false;
        }
      }
    }
    c = b.child;
    if (b.subtreeFlags & 16384 && null !== c) c.return = b, b = c;
    else {
      if (b === a) break;
      for (; null === b.sibling; ) {
        if (null === b.return || b.return === a) return true;
        b = b.return;
      }
      b.sibling.return = b.return;
      b = b.sibling;
    }
  }
  return true;
}
function Ck(a, b) {
  b &= ~rk;
  b &= ~qk;
  a.suspendedLanes |= b;
  a.pingedLanes &= ~b;
  for (a = a.expirationTimes; 0 < b; ) {
    var c = 31 - oc(b), d = 1 << c;
    a[c] = -1;
    b &= ~d;
  }
}
function Ek(a) {
  if (0 !== (K & 6)) throw Error(p(327));
  Hk();
  var b = uc(a, 0);
  if (0 === (b & 1)) return Dk(a, B()), null;
  var c = Ik(a, b);
  if (0 !== a.tag && 2 === c) {
    var d = xc(a);
    0 !== d && (b = d, c = Nk(a, d));
  }
  if (1 === c) throw c = pk, Kk(a, 0), Ck(a, b), Dk(a, B()), c;
  if (6 === c) throw Error(p(345));
  a.finishedWork = a.current.alternate;
  a.finishedLanes = b;
  Pk(a, tk, uk);
  Dk(a, B());
  return null;
}
function Qk(a, b) {
  var c = K;
  K |= 1;
  try {
    return a(b);
  } finally {
    K = c, 0 === K && (Gj = B() + 500, fg && jg());
  }
}
function Rk(a) {
  null !== wk && 0 === wk.tag && 0 === (K & 6) && Hk();
  var b = K;
  K |= 1;
  var c = ok.transition, d = C;
  try {
    if (ok.transition = null, C = 1, a) return a();
  } finally {
    C = d, ok.transition = c, K = b, 0 === (K & 6) && jg();
  }
}
function Hj() {
  fj = ej.current;
  E(ej);
}
function Kk(a, b) {
  a.finishedWork = null;
  a.finishedLanes = 0;
  var c = a.timeoutHandle;
  -1 !== c && (a.timeoutHandle = -1, Gf(c));
  if (null !== Y$1) for (c = Y$1.return; null !== c; ) {
    var d = c;
    wg(d);
    switch (d.tag) {
      case 1:
        d = d.type.childContextTypes;
        null !== d && void 0 !== d && $f();
        break;
      case 3:
        zh();
        E(Wf);
        E(H$1);
        Eh();
        break;
      case 5:
        Bh(d);
        break;
      case 4:
        zh();
        break;
      case 13:
        E(L);
        break;
      case 19:
        E(L);
        break;
      case 10:
        ah(d.type._context);
        break;
      case 22:
      case 23:
        Hj();
    }
    c = c.return;
  }
  Q = a;
  Y$1 = a = Pg(a.current, null);
  Z$1 = fj = b;
  T = 0;
  pk = null;
  rk = qk = rh = 0;
  tk = sk = null;
  if (null !== fh) {
    for (b = 0; b < fh.length; b++) if (c = fh[b], d = c.interleaved, null !== d) {
      c.interleaved = null;
      var e = d.next, f2 = c.pending;
      if (null !== f2) {
        var g = f2.next;
        f2.next = e;
        d.next = g;
      }
      c.pending = d;
    }
    fh = null;
  }
  return a;
}
function Mk(a, b) {
  do {
    var c = Y$1;
    try {
      $g();
      Fh.current = Rh;
      if (Ih) {
        for (var d = M.memoizedState; null !== d; ) {
          var e = d.queue;
          null !== e && (e.pending = null);
          d = d.next;
        }
        Ih = false;
      }
      Hh = 0;
      O = N = M = null;
      Jh = false;
      Kh = 0;
      nk.current = null;
      if (null === c || null === c.return) {
        T = 1;
        pk = b;
        Y$1 = null;
        break;
      }
      a: {
        var f2 = a, g = c.return, h2 = c, k2 = b;
        b = Z$1;
        h2.flags |= 32768;
        if (null !== k2 && "object" === typeof k2 && "function" === typeof k2.then) {
          var l2 = k2, m2 = h2, q2 = m2.tag;
          if (0 === (m2.mode & 1) && (0 === q2 || 11 === q2 || 15 === q2)) {
            var r2 = m2.alternate;
            r2 ? (m2.updateQueue = r2.updateQueue, m2.memoizedState = r2.memoizedState, m2.lanes = r2.lanes) : (m2.updateQueue = null, m2.memoizedState = null);
          }
          var y2 = Ui(g);
          if (null !== y2) {
            y2.flags &= -257;
            Vi(y2, g, h2, f2, b);
            y2.mode & 1 && Si(f2, l2, b);
            b = y2;
            k2 = l2;
            var n2 = b.updateQueue;
            if (null === n2) {
              var t2 = /* @__PURE__ */ new Set();
              t2.add(k2);
              b.updateQueue = t2;
            } else n2.add(k2);
            break a;
          } else {
            if (0 === (b & 1)) {
              Si(f2, l2, b);
              tj();
              break a;
            }
            k2 = Error(p(426));
          }
        } else if (I && h2.mode & 1) {
          var J2 = Ui(g);
          if (null !== J2) {
            0 === (J2.flags & 65536) && (J2.flags |= 256);
            Vi(J2, g, h2, f2, b);
            Jg(Ji(k2, h2));
            break a;
          }
        }
        f2 = k2 = Ji(k2, h2);
        4 !== T && (T = 2);
        null === sk ? sk = [f2] : sk.push(f2);
        f2 = g;
        do {
          switch (f2.tag) {
            case 3:
              f2.flags |= 65536;
              b &= -b;
              f2.lanes |= b;
              var x2 = Ni(f2, k2, b);
              ph(f2, x2);
              break a;
            case 1:
              h2 = k2;
              var w2 = f2.type, u2 = f2.stateNode;
              if (0 === (f2.flags & 128) && ("function" === typeof w2.getDerivedStateFromError || null !== u2 && "function" === typeof u2.componentDidCatch && (null === Ri || !Ri.has(u2)))) {
                f2.flags |= 65536;
                b &= -b;
                f2.lanes |= b;
                var F2 = Qi(f2, h2, b);
                ph(f2, F2);
                break a;
              }
          }
          f2 = f2.return;
        } while (null !== f2);
      }
      Sk(c);
    } catch (na) {
      b = na;
      Y$1 === c && null !== c && (Y$1 = c = c.return);
      continue;
    }
    break;
  } while (1);
}
function Jk() {
  var a = mk.current;
  mk.current = Rh;
  return null === a ? Rh : a;
}
function tj() {
  if (0 === T || 3 === T || 2 === T) T = 4;
  null === Q || 0 === (rh & 268435455) && 0 === (qk & 268435455) || Ck(Q, Z$1);
}
function Ik(a, b) {
  var c = K;
  K |= 2;
  var d = Jk();
  if (Q !== a || Z$1 !== b) uk = null, Kk(a, b);
  do
    try {
      Tk();
      break;
    } catch (e) {
      Mk(a, e);
    }
  while (1);
  $g();
  K = c;
  mk.current = d;
  if (null !== Y$1) throw Error(p(261));
  Q = null;
  Z$1 = 0;
  return T;
}
function Tk() {
  for (; null !== Y$1; ) Uk(Y$1);
}
function Lk() {
  for (; null !== Y$1 && !cc(); ) Uk(Y$1);
}
function Uk(a) {
  var b = Vk(a.alternate, a, fj);
  a.memoizedProps = a.pendingProps;
  null === b ? Sk(a) : Y$1 = b;
  nk.current = null;
}
function Sk(a) {
  var b = a;
  do {
    var c = b.alternate;
    a = b.return;
    if (0 === (b.flags & 32768)) {
      if (c = Ej(c, b, fj), null !== c) {
        Y$1 = c;
        return;
      }
    } else {
      c = Ij(c, b);
      if (null !== c) {
        c.flags &= 32767;
        Y$1 = c;
        return;
      }
      if (null !== a) a.flags |= 32768, a.subtreeFlags = 0, a.deletions = null;
      else {
        T = 6;
        Y$1 = null;
        return;
      }
    }
    b = b.sibling;
    if (null !== b) {
      Y$1 = b;
      return;
    }
    Y$1 = b = a;
  } while (null !== b);
  0 === T && (T = 5);
}
function Pk(a, b, c) {
  var d = C, e = ok.transition;
  try {
    ok.transition = null, C = 1, Wk(a, b, c, d);
  } finally {
    ok.transition = e, C = d;
  }
  return null;
}
function Wk(a, b, c, d) {
  do
    Hk();
  while (null !== wk);
  if (0 !== (K & 6)) throw Error(p(327));
  c = a.finishedWork;
  var e = a.finishedLanes;
  if (null === c) return null;
  a.finishedWork = null;
  a.finishedLanes = 0;
  if (c === a.current) throw Error(p(177));
  a.callbackNode = null;
  a.callbackPriority = 0;
  var f2 = c.lanes | c.childLanes;
  Bc(a, f2);
  a === Q && (Y$1 = Q = null, Z$1 = 0);
  0 === (c.subtreeFlags & 2064) && 0 === (c.flags & 2064) || vk || (vk = true, Fk(hc, function() {
    Hk();
    return null;
  }));
  f2 = 0 !== (c.flags & 15990);
  if (0 !== (c.subtreeFlags & 15990) || f2) {
    f2 = ok.transition;
    ok.transition = null;
    var g = C;
    C = 1;
    var h2 = K;
    K |= 4;
    nk.current = null;
    Oj(a, c);
    dk(c, a);
    Oe$1(Df);
    dd = !!Cf;
    Df = Cf = null;
    a.current = c;
    hk(c);
    dc();
    K = h2;
    C = g;
    ok.transition = f2;
  } else a.current = c;
  vk && (vk = false, wk = a, xk = e);
  f2 = a.pendingLanes;
  0 === f2 && (Ri = null);
  mc(c.stateNode);
  Dk(a, B());
  if (null !== b) for (d = a.onRecoverableError, c = 0; c < b.length; c++) e = b[c], d(e.value, { componentStack: e.stack, digest: e.digest });
  if (Oi) throw Oi = false, a = Pi, Pi = null, a;
  0 !== (xk & 1) && 0 !== a.tag && Hk();
  f2 = a.pendingLanes;
  0 !== (f2 & 1) ? a === zk ? yk++ : (yk = 0, zk = a) : yk = 0;
  jg();
  return null;
}
function Hk() {
  if (null !== wk) {
    var a = Dc(xk), b = ok.transition, c = C;
    try {
      ok.transition = null;
      C = 16 > a ? 16 : a;
      if (null === wk) var d = false;
      else {
        a = wk;
        wk = null;
        xk = 0;
        if (0 !== (K & 6)) throw Error(p(331));
        var e = K;
        K |= 4;
        for (V = a.current; null !== V; ) {
          var f2 = V, g = f2.child;
          if (0 !== (V.flags & 16)) {
            var h2 = f2.deletions;
            if (null !== h2) {
              for (var k2 = 0; k2 < h2.length; k2++) {
                var l2 = h2[k2];
                for (V = l2; null !== V; ) {
                  var m2 = V;
                  switch (m2.tag) {
                    case 0:
                    case 11:
                    case 15:
                      Pj(8, m2, f2);
                  }
                  var q2 = m2.child;
                  if (null !== q2) q2.return = m2, V = q2;
                  else for (; null !== V; ) {
                    m2 = V;
                    var r2 = m2.sibling, y2 = m2.return;
                    Sj(m2);
                    if (m2 === l2) {
                      V = null;
                      break;
                    }
                    if (null !== r2) {
                      r2.return = y2;
                      V = r2;
                      break;
                    }
                    V = y2;
                  }
                }
              }
              var n2 = f2.alternate;
              if (null !== n2) {
                var t2 = n2.child;
                if (null !== t2) {
                  n2.child = null;
                  do {
                    var J2 = t2.sibling;
                    t2.sibling = null;
                    t2 = J2;
                  } while (null !== t2);
                }
              }
              V = f2;
            }
          }
          if (0 !== (f2.subtreeFlags & 2064) && null !== g) g.return = f2, V = g;
          else b: for (; null !== V; ) {
            f2 = V;
            if (0 !== (f2.flags & 2048)) switch (f2.tag) {
              case 0:
              case 11:
              case 15:
                Pj(9, f2, f2.return);
            }
            var x2 = f2.sibling;
            if (null !== x2) {
              x2.return = f2.return;
              V = x2;
              break b;
            }
            V = f2.return;
          }
        }
        var w2 = a.current;
        for (V = w2; null !== V; ) {
          g = V;
          var u2 = g.child;
          if (0 !== (g.subtreeFlags & 2064) && null !== u2) u2.return = g, V = u2;
          else b: for (g = w2; null !== V; ) {
            h2 = V;
            if (0 !== (h2.flags & 2048)) try {
              switch (h2.tag) {
                case 0:
                case 11:
                case 15:
                  Qj(9, h2);
              }
            } catch (na) {
              W(h2, h2.return, na);
            }
            if (h2 === g) {
              V = null;
              break b;
            }
            var F2 = h2.sibling;
            if (null !== F2) {
              F2.return = h2.return;
              V = F2;
              break b;
            }
            V = h2.return;
          }
        }
        K = e;
        jg();
        if (lc && "function" === typeof lc.onPostCommitFiberRoot) try {
          lc.onPostCommitFiberRoot(kc, a);
        } catch (na) {
        }
        d = true;
      }
      return d;
    } finally {
      C = c, ok.transition = b;
    }
  }
  return false;
}
function Xk(a, b, c) {
  b = Ji(c, b);
  b = Ni(a, b, 1);
  a = nh(a, b, 1);
  b = R();
  null !== a && (Ac(a, 1, b), Dk(a, b));
}
function W(a, b, c) {
  if (3 === a.tag) Xk(a, a, c);
  else for (; null !== b; ) {
    if (3 === b.tag) {
      Xk(b, a, c);
      break;
    } else if (1 === b.tag) {
      var d = b.stateNode;
      if ("function" === typeof b.type.getDerivedStateFromError || "function" === typeof d.componentDidCatch && (null === Ri || !Ri.has(d))) {
        a = Ji(c, a);
        a = Qi(b, a, 1);
        b = nh(b, a, 1);
        a = R();
        null !== b && (Ac(b, 1, a), Dk(b, a));
        break;
      }
    }
    b = b.return;
  }
}
function Ti(a, b, c) {
  var d = a.pingCache;
  null !== d && d.delete(b);
  b = R();
  a.pingedLanes |= a.suspendedLanes & c;
  Q === a && (Z$1 & c) === c && (4 === T || 3 === T && (Z$1 & 130023424) === Z$1 && 500 > B() - fk ? Kk(a, 0) : rk |= c);
  Dk(a, b);
}
function Yk(a, b) {
  0 === b && (0 === (a.mode & 1) ? b = 1 : (b = sc, sc <<= 1, 0 === (sc & 130023424) && (sc = 4194304)));
  var c = R();
  a = ih(a, b);
  null !== a && (Ac(a, b, c), Dk(a, c));
}
function uj(a) {
  var b = a.memoizedState, c = 0;
  null !== b && (c = b.retryLane);
  Yk(a, c);
}
function bk(a, b) {
  var c = 0;
  switch (a.tag) {
    case 13:
      var d = a.stateNode;
      var e = a.memoizedState;
      null !== e && (c = e.retryLane);
      break;
    case 19:
      d = a.stateNode;
      break;
    default:
      throw Error(p(314));
  }
  null !== d && d.delete(b);
  Yk(a, c);
}
var Vk;
Vk = function(a, b, c) {
  if (null !== a) if (a.memoizedProps !== b.pendingProps || Wf.current) dh = true;
  else {
    if (0 === (a.lanes & c) && 0 === (b.flags & 128)) return dh = false, yj(a, b, c);
    dh = 0 !== (a.flags & 131072) ? true : false;
  }
  else dh = false, I && 0 !== (b.flags & 1048576) && ug(b, ng, b.index);
  b.lanes = 0;
  switch (b.tag) {
    case 2:
      var d = b.type;
      ij(a, b);
      a = b.pendingProps;
      var e = Yf(b, H$1.current);
      ch(b, c);
      e = Nh(null, b, d, a, e, c);
      var f2 = Sh();
      b.flags |= 1;
      "object" === typeof e && null !== e && "function" === typeof e.render && void 0 === e.$$typeof ? (b.tag = 1, b.memoizedState = null, b.updateQueue = null, Zf(d) ? (f2 = true, cg(b)) : f2 = false, b.memoizedState = null !== e.state && void 0 !== e.state ? e.state : null, kh(b), e.updater = Ei, b.stateNode = e, e._reactInternals = b, Ii(b, d, a, c), b = jj(null, b, d, true, f2, c)) : (b.tag = 0, I && f2 && vg(b), Xi(null, b, e, c), b = b.child);
      return b;
    case 16:
      d = b.elementType;
      a: {
        ij(a, b);
        a = b.pendingProps;
        e = d._init;
        d = e(d._payload);
        b.type = d;
        e = b.tag = Zk(d);
        a = Ci(d, a);
        switch (e) {
          case 0:
            b = cj(null, b, d, a, c);
            break a;
          case 1:
            b = hj(null, b, d, a, c);
            break a;
          case 11:
            b = Yi(null, b, d, a, c);
            break a;
          case 14:
            b = $i(null, b, d, Ci(d.type, a), c);
            break a;
        }
        throw Error(p(
          306,
          d,
          ""
        ));
      }
      return b;
    case 0:
      return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : Ci(d, e), cj(a, b, d, e, c);
    case 1:
      return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : Ci(d, e), hj(a, b, d, e, c);
    case 3:
      a: {
        kj(b);
        if (null === a) throw Error(p(387));
        d = b.pendingProps;
        f2 = b.memoizedState;
        e = f2.element;
        lh(a, b);
        qh(b, d, null, c);
        var g = b.memoizedState;
        d = g.element;
        if (f2.isDehydrated) if (f2 = { element: d, isDehydrated: false, cache: g.cache, pendingSuspenseBoundaries: g.pendingSuspenseBoundaries, transitions: g.transitions }, b.updateQueue.baseState = f2, b.memoizedState = f2, b.flags & 256) {
          e = Ji(Error(p(423)), b);
          b = lj(a, b, d, c, e);
          break a;
        } else if (d !== e) {
          e = Ji(Error(p(424)), b);
          b = lj(a, b, d, c, e);
          break a;
        } else for (yg = Lf(b.stateNode.containerInfo.firstChild), xg = b, I = true, zg = null, c = Vg(b, null, d, c), b.child = c; c; ) c.flags = c.flags & -3 | 4096, c = c.sibling;
        else {
          Ig();
          if (d === e) {
            b = Zi(a, b, c);
            break a;
          }
          Xi(a, b, d, c);
        }
        b = b.child;
      }
      return b;
    case 5:
      return Ah(b), null === a && Eg(b), d = b.type, e = b.pendingProps, f2 = null !== a ? a.memoizedProps : null, g = e.children, Ef(d, e) ? g = null : null !== f2 && Ef(d, f2) && (b.flags |= 32), gj(a, b), Xi(a, b, g, c), b.child;
    case 6:
      return null === a && Eg(b), null;
    case 13:
      return oj(a, b, c);
    case 4:
      return yh(b, b.stateNode.containerInfo), d = b.pendingProps, null === a ? b.child = Ug(b, null, d, c) : Xi(a, b, d, c), b.child;
    case 11:
      return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : Ci(d, e), Yi(a, b, d, e, c);
    case 7:
      return Xi(a, b, b.pendingProps, c), b.child;
    case 8:
      return Xi(a, b, b.pendingProps.children, c), b.child;
    case 12:
      return Xi(a, b, b.pendingProps.children, c), b.child;
    case 10:
      a: {
        d = b.type._context;
        e = b.pendingProps;
        f2 = b.memoizedProps;
        g = e.value;
        G(Wg, d._currentValue);
        d._currentValue = g;
        if (null !== f2) if (He$1(f2.value, g)) {
          if (f2.children === e.children && !Wf.current) {
            b = Zi(a, b, c);
            break a;
          }
        } else for (f2 = b.child, null !== f2 && (f2.return = b); null !== f2; ) {
          var h2 = f2.dependencies;
          if (null !== h2) {
            g = f2.child;
            for (var k2 = h2.firstContext; null !== k2; ) {
              if (k2.context === d) {
                if (1 === f2.tag) {
                  k2 = mh(-1, c & -c);
                  k2.tag = 2;
                  var l2 = f2.updateQueue;
                  if (null !== l2) {
                    l2 = l2.shared;
                    var m2 = l2.pending;
                    null === m2 ? k2.next = k2 : (k2.next = m2.next, m2.next = k2);
                    l2.pending = k2;
                  }
                }
                f2.lanes |= c;
                k2 = f2.alternate;
                null !== k2 && (k2.lanes |= c);
                bh(
                  f2.return,
                  c,
                  b
                );
                h2.lanes |= c;
                break;
              }
              k2 = k2.next;
            }
          } else if (10 === f2.tag) g = f2.type === b.type ? null : f2.child;
          else if (18 === f2.tag) {
            g = f2.return;
            if (null === g) throw Error(p(341));
            g.lanes |= c;
            h2 = g.alternate;
            null !== h2 && (h2.lanes |= c);
            bh(g, c, b);
            g = f2.sibling;
          } else g = f2.child;
          if (null !== g) g.return = f2;
          else for (g = f2; null !== g; ) {
            if (g === b) {
              g = null;
              break;
            }
            f2 = g.sibling;
            if (null !== f2) {
              f2.return = g.return;
              g = f2;
              break;
            }
            g = g.return;
          }
          f2 = g;
        }
        Xi(a, b, e.children, c);
        b = b.child;
      }
      return b;
    case 9:
      return e = b.type, d = b.pendingProps.children, ch(b, c), e = eh(e), d = d(e), b.flags |= 1, Xi(a, b, d, c), b.child;
    case 14:
      return d = b.type, e = Ci(d, b.pendingProps), e = Ci(d.type, e), $i(a, b, d, e, c);
    case 15:
      return bj(a, b, b.type, b.pendingProps, c);
    case 17:
      return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : Ci(d, e), ij(a, b), b.tag = 1, Zf(d) ? (a = true, cg(b)) : a = false, ch(b, c), Gi(b, d, e), Ii(b, d, e, c), jj(null, b, d, true, a, c);
    case 19:
      return xj(a, b, c);
    case 22:
      return dj(a, b, c);
  }
  throw Error(p(156, b.tag));
};
function Fk(a, b) {
  return ac(a, b);
}
function $k(a, b, c, d) {
  this.tag = a;
  this.key = c;
  this.sibling = this.child = this.return = this.stateNode = this.type = this.elementType = null;
  this.index = 0;
  this.ref = null;
  this.pendingProps = b;
  this.dependencies = this.memoizedState = this.updateQueue = this.memoizedProps = null;
  this.mode = d;
  this.subtreeFlags = this.flags = 0;
  this.deletions = null;
  this.childLanes = this.lanes = 0;
  this.alternate = null;
}
function Bg(a, b, c, d) {
  return new $k(a, b, c, d);
}
function aj(a) {
  a = a.prototype;
  return !(!a || !a.isReactComponent);
}
function Zk(a) {
  if ("function" === typeof a) return aj(a) ? 1 : 0;
  if (void 0 !== a && null !== a) {
    a = a.$$typeof;
    if (a === Da) return 11;
    if (a === Ga) return 14;
  }
  return 2;
}
function Pg(a, b) {
  var c = a.alternate;
  null === c ? (c = Bg(a.tag, b, a.key, a.mode), c.elementType = a.elementType, c.type = a.type, c.stateNode = a.stateNode, c.alternate = a, a.alternate = c) : (c.pendingProps = b, c.type = a.type, c.flags = 0, c.subtreeFlags = 0, c.deletions = null);
  c.flags = a.flags & 14680064;
  c.childLanes = a.childLanes;
  c.lanes = a.lanes;
  c.child = a.child;
  c.memoizedProps = a.memoizedProps;
  c.memoizedState = a.memoizedState;
  c.updateQueue = a.updateQueue;
  b = a.dependencies;
  c.dependencies = null === b ? null : { lanes: b.lanes, firstContext: b.firstContext };
  c.sibling = a.sibling;
  c.index = a.index;
  c.ref = a.ref;
  return c;
}
function Rg(a, b, c, d, e, f2) {
  var g = 2;
  d = a;
  if ("function" === typeof a) aj(a) && (g = 1);
  else if ("string" === typeof a) g = 5;
  else a: switch (a) {
    case ya:
      return Tg(c.children, e, f2, b);
    case za:
      g = 8;
      e |= 8;
      break;
    case Aa:
      return a = Bg(12, c, b, e | 2), a.elementType = Aa, a.lanes = f2, a;
    case Ea:
      return a = Bg(13, c, b, e), a.elementType = Ea, a.lanes = f2, a;
    case Fa:
      return a = Bg(19, c, b, e), a.elementType = Fa, a.lanes = f2, a;
    case Ia:
      return pj(c, e, f2, b);
    default:
      if ("object" === typeof a && null !== a) switch (a.$$typeof) {
        case Ba:
          g = 10;
          break a;
        case Ca:
          g = 9;
          break a;
        case Da:
          g = 11;
          break a;
        case Ga:
          g = 14;
          break a;
        case Ha:
          g = 16;
          d = null;
          break a;
      }
      throw Error(p(130, null == a ? a : typeof a, ""));
  }
  b = Bg(g, c, b, e);
  b.elementType = a;
  b.type = d;
  b.lanes = f2;
  return b;
}
function Tg(a, b, c, d) {
  a = Bg(7, a, d, b);
  a.lanes = c;
  return a;
}
function pj(a, b, c, d) {
  a = Bg(22, a, d, b);
  a.elementType = Ia;
  a.lanes = c;
  a.stateNode = { isHidden: false };
  return a;
}
function Qg(a, b, c) {
  a = Bg(6, a, null, b);
  a.lanes = c;
  return a;
}
function Sg(a, b, c) {
  b = Bg(4, null !== a.children ? a.children : [], a.key, b);
  b.lanes = c;
  b.stateNode = { containerInfo: a.containerInfo, pendingChildren: null, implementation: a.implementation };
  return b;
}
function al(a, b, c, d, e) {
  this.tag = b;
  this.containerInfo = a;
  this.finishedWork = this.pingCache = this.current = this.pendingChildren = null;
  this.timeoutHandle = -1;
  this.callbackNode = this.pendingContext = this.context = null;
  this.callbackPriority = 0;
  this.eventTimes = zc(0);
  this.expirationTimes = zc(-1);
  this.entangledLanes = this.finishedLanes = this.mutableReadLanes = this.expiredLanes = this.pingedLanes = this.suspendedLanes = this.pendingLanes = 0;
  this.entanglements = zc(0);
  this.identifierPrefix = d;
  this.onRecoverableError = e;
  this.mutableSourceEagerHydrationData = null;
}
function bl(a, b, c, d, e, f2, g, h2, k2) {
  a = new al(a, b, c, h2, k2);
  1 === b ? (b = 1, true === f2 && (b |= 8)) : b = 0;
  f2 = Bg(3, null, null, b);
  a.current = f2;
  f2.stateNode = a;
  f2.memoizedState = { element: d, isDehydrated: c, cache: null, transitions: null, pendingSuspenseBoundaries: null };
  kh(f2);
  return a;
}
function cl(a, b, c) {
  var d = 3 < arguments.length && void 0 !== arguments[3] ? arguments[3] : null;
  return { $$typeof: wa, key: null == d ? null : "" + d, children: a, containerInfo: b, implementation: c };
}
function dl(a) {
  if (!a) return Vf;
  a = a._reactInternals;
  a: {
    if (Vb(a) !== a || 1 !== a.tag) throw Error(p(170));
    var b = a;
    do {
      switch (b.tag) {
        case 3:
          b = b.stateNode.context;
          break a;
        case 1:
          if (Zf(b.type)) {
            b = b.stateNode.__reactInternalMemoizedMergedChildContext;
            break a;
          }
      }
      b = b.return;
    } while (null !== b);
    throw Error(p(171));
  }
  if (1 === a.tag) {
    var c = a.type;
    if (Zf(c)) return bg(a, c, b);
  }
  return b;
}
function el(a, b, c, d, e, f2, g, h2, k2) {
  a = bl(c, d, true, a, e, f2, g, h2, k2);
  a.context = dl(null);
  c = a.current;
  d = R();
  e = yi(c);
  f2 = mh(d, e);
  f2.callback = void 0 !== b && null !== b ? b : null;
  nh(c, f2, e);
  a.current.lanes = e;
  Ac(a, e, d);
  Dk(a, d);
  return a;
}
function fl(a, b, c, d) {
  var e = b.current, f2 = R(), g = yi(e);
  c = dl(c);
  null === b.context ? b.context = c : b.pendingContext = c;
  b = mh(f2, g);
  b.payload = { element: a };
  d = void 0 === d ? null : d;
  null !== d && (b.callback = d);
  a = nh(e, b, g);
  null !== a && (gi(a, e, g, f2), oh(a, e, g));
  return g;
}
function gl(a) {
  a = a.current;
  if (!a.child) return null;
  switch (a.child.tag) {
    case 5:
      return a.child.stateNode;
    default:
      return a.child.stateNode;
  }
}
function hl(a, b) {
  a = a.memoizedState;
  if (null !== a && null !== a.dehydrated) {
    var c = a.retryLane;
    a.retryLane = 0 !== c && c < b ? c : b;
  }
}
function il(a, b) {
  hl(a, b);
  (a = a.alternate) && hl(a, b);
}
function jl() {
  return null;
}
var kl = "function" === typeof reportError ? reportError : function(a) {
  console.error(a);
};
function ll(a) {
  this._internalRoot = a;
}
ml.prototype.render = ll.prototype.render = function(a) {
  var b = this._internalRoot;
  if (null === b) throw Error(p(409));
  fl(a, b, null, null);
};
ml.prototype.unmount = ll.prototype.unmount = function() {
  var a = this._internalRoot;
  if (null !== a) {
    this._internalRoot = null;
    var b = a.containerInfo;
    Rk(function() {
      fl(null, a, null, null);
    });
    b[uf] = null;
  }
};
function ml(a) {
  this._internalRoot = a;
}
ml.prototype.unstable_scheduleHydration = function(a) {
  if (a) {
    var b = Hc();
    a = { blockedOn: null, target: a, priority: b };
    for (var c = 0; c < Qc.length && 0 !== b && b < Qc[c].priority; c++) ;
    Qc.splice(c, 0, a);
    0 === c && Vc(a);
  }
};
function nl(a) {
  return !(!a || 1 !== a.nodeType && 9 !== a.nodeType && 11 !== a.nodeType);
}
function ol(a) {
  return !(!a || 1 !== a.nodeType && 9 !== a.nodeType && 11 !== a.nodeType && (8 !== a.nodeType || " react-mount-point-unstable " !== a.nodeValue));
}
function pl() {
}
function ql(a, b, c, d, e) {
  if (e) {
    if ("function" === typeof d) {
      var f2 = d;
      d = function() {
        var a2 = gl(g);
        f2.call(a2);
      };
    }
    var g = el(b, d, a, 0, null, false, false, "", pl);
    a._reactRootContainer = g;
    a[uf] = g.current;
    sf(8 === a.nodeType ? a.parentNode : a);
    Rk();
    return g;
  }
  for (; e = a.lastChild; ) a.removeChild(e);
  if ("function" === typeof d) {
    var h2 = d;
    d = function() {
      var a2 = gl(k2);
      h2.call(a2);
    };
  }
  var k2 = bl(a, 0, false, null, null, false, false, "", pl);
  a._reactRootContainer = k2;
  a[uf] = k2.current;
  sf(8 === a.nodeType ? a.parentNode : a);
  Rk(function() {
    fl(b, k2, c, d);
  });
  return k2;
}
function rl(a, b, c, d, e) {
  var f2 = c._reactRootContainer;
  if (f2) {
    var g = f2;
    if ("function" === typeof e) {
      var h2 = e;
      e = function() {
        var a2 = gl(g);
        h2.call(a2);
      };
    }
    fl(b, g, a, e);
  } else g = ql(c, b, a, e, d);
  return gl(g);
}
Ec = function(a) {
  switch (a.tag) {
    case 3:
      var b = a.stateNode;
      if (b.current.memoizedState.isDehydrated) {
        var c = tc(b.pendingLanes);
        0 !== c && (Cc(b, c | 1), Dk(b, B()), 0 === (K & 6) && (Gj = B() + 500, jg()));
      }
      break;
    case 13:
      Rk(function() {
        var b2 = ih(a, 1);
        if (null !== b2) {
          var c2 = R();
          gi(b2, a, 1, c2);
        }
      }), il(a, 1);
  }
};
Fc = function(a) {
  if (13 === a.tag) {
    var b = ih(a, 134217728);
    if (null !== b) {
      var c = R();
      gi(b, a, 134217728, c);
    }
    il(a, 134217728);
  }
};
Gc = function(a) {
  if (13 === a.tag) {
    var b = yi(a), c = ih(a, b);
    if (null !== c) {
      var d = R();
      gi(c, a, b, d);
    }
    il(a, b);
  }
};
Hc = function() {
  return C;
};
Ic = function(a, b) {
  var c = C;
  try {
    return C = a, b();
  } finally {
    C = c;
  }
};
yb = function(a, b, c) {
  switch (b) {
    case "input":
      bb(a, c);
      b = c.name;
      if ("radio" === c.type && null != b) {
        for (c = a; c.parentNode; ) c = c.parentNode;
        c = c.querySelectorAll("input[name=" + JSON.stringify("" + b) + '][type="radio"]');
        for (b = 0; b < c.length; b++) {
          var d = c[b];
          if (d !== a && d.form === a.form) {
            var e = Db(d);
            if (!e) throw Error(p(90));
            Wa(d);
            bb(d, e);
          }
        }
      }
      break;
    case "textarea":
      ib(a, c);
      break;
    case "select":
      b = c.value, null != b && fb(a, !!c.multiple, b, false);
  }
};
Gb = Qk;
Hb = Rk;
var sl = { usingClientEntryPoint: false, Events: [Cb, ue, Db, Eb, Fb, Qk] }, tl = { findFiberByHostInstance: Wc, bundleType: 0, version: "18.3.1", rendererPackageName: "react-dom" };
var ul = { bundleType: tl.bundleType, version: tl.version, rendererPackageName: tl.rendererPackageName, rendererConfig: tl.rendererConfig, overrideHookState: null, overrideHookStateDeletePath: null, overrideHookStateRenamePath: null, overrideProps: null, overridePropsDeletePath: null, overridePropsRenamePath: null, setErrorHandler: null, setSuspenseHandler: null, scheduleUpdate: null, currentDispatcherRef: ua.ReactCurrentDispatcher, findHostInstanceByFiber: function(a) {
  a = Zb(a);
  return null === a ? null : a.stateNode;
}, findFiberByHostInstance: tl.findFiberByHostInstance || jl, findHostInstancesForRefresh: null, scheduleRefresh: null, scheduleRoot: null, setRefreshHandler: null, getCurrentFiber: null, reconcilerVersion: "18.3.1-next-f1338f8080-20240426" };
if ("undefined" !== typeof __REACT_DEVTOOLS_GLOBAL_HOOK__) {
  var vl = __REACT_DEVTOOLS_GLOBAL_HOOK__;
  if (!vl.isDisabled && vl.supportsFiber) try {
    kc = vl.inject(ul), lc = vl;
  } catch (a) {
  }
}
reactDom_production_min.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED = sl;
reactDom_production_min.createPortal = function(a, b) {
  var c = 2 < arguments.length && void 0 !== arguments[2] ? arguments[2] : null;
  if (!nl(b)) throw Error(p(200));
  return cl(a, b, null, c);
};
reactDom_production_min.createRoot = function(a, b) {
  if (!nl(a)) throw Error(p(299));
  var c = false, d = "", e = kl;
  null !== b && void 0 !== b && (true === b.unstable_strictMode && (c = true), void 0 !== b.identifierPrefix && (d = b.identifierPrefix), void 0 !== b.onRecoverableError && (e = b.onRecoverableError));
  b = bl(a, 1, false, null, null, c, false, d, e);
  a[uf] = b.current;
  sf(8 === a.nodeType ? a.parentNode : a);
  return new ll(b);
};
reactDom_production_min.findDOMNode = function(a) {
  if (null == a) return null;
  if (1 === a.nodeType) return a;
  var b = a._reactInternals;
  if (void 0 === b) {
    if ("function" === typeof a.render) throw Error(p(188));
    a = Object.keys(a).join(",");
    throw Error(p(268, a));
  }
  a = Zb(b);
  a = null === a ? null : a.stateNode;
  return a;
};
reactDom_production_min.flushSync = function(a) {
  return Rk(a);
};
reactDom_production_min.hydrate = function(a, b, c) {
  if (!ol(b)) throw Error(p(200));
  return rl(null, a, b, true, c);
};
reactDom_production_min.hydrateRoot = function(a, b, c) {
  if (!nl(a)) throw Error(p(405));
  var d = null != c && c.hydratedSources || null, e = false, f2 = "", g = kl;
  null !== c && void 0 !== c && (true === c.unstable_strictMode && (e = true), void 0 !== c.identifierPrefix && (f2 = c.identifierPrefix), void 0 !== c.onRecoverableError && (g = c.onRecoverableError));
  b = el(b, null, a, 1, null != c ? c : null, e, false, f2, g);
  a[uf] = b.current;
  sf(a);
  if (d) for (a = 0; a < d.length; a++) c = d[a], e = c._getVersion, e = e(c._source), null == b.mutableSourceEagerHydrationData ? b.mutableSourceEagerHydrationData = [c, e] : b.mutableSourceEagerHydrationData.push(
    c,
    e
  );
  return new ml(b);
};
reactDom_production_min.render = function(a, b, c) {
  if (!ol(b)) throw Error(p(200));
  return rl(null, a, b, false, c);
};
reactDom_production_min.unmountComponentAtNode = function(a) {
  if (!ol(a)) throw Error(p(40));
  return a._reactRootContainer ? (Rk(function() {
    rl(null, null, a, false, function() {
      a._reactRootContainer = null;
      a[uf] = null;
    });
  }), true) : false;
};
reactDom_production_min.unstable_batchedUpdates = Qk;
reactDom_production_min.unstable_renderSubtreeIntoContainer = function(a, b, c, d) {
  if (!ol(c)) throw Error(p(200));
  if (null == a || void 0 === a._reactInternals) throw Error(p(38));
  return rl(a, b, c, false, d);
};
reactDom_production_min.version = "18.3.1-next-f1338f8080-20240426";
function checkDCE() {
  if (typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ === "undefined" || typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE !== "function") {
    return;
  }
  try {
    __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(checkDCE);
  } catch (err) {
    console.error(err);
  }
}
{
  checkDCE();
  reactDom.exports = reactDom_production_min;
}
var reactDomExports = reactDom.exports;
var m = reactDomExports;
{
  client.createRoot = m.createRoot;
  client.hydrateRoot = m.hydrateRoot;
}
const AppContext = reactExports.createContext(null);
const MODEL_INVENTORY_TTL_MS = 60 * 1e3;
const OLLAMA_MODELS_TTL_MS = 30 * 1e3;
function normalizeView(view) {
  switch (view) {
    case "chat":
      return "studio";
    case "files":
    case "git":
    case "project":
      return "developer";
    case "agents":
      return "build";
    case "mcp":
      return "integrations";
    case "skills":
      return "marketplace";
    case "models":
    case "docs":
      return "settings";
    case "orchestration":
      return "runs";
    default:
      return view || "home";
  }
}
const initialState = {
  // App mode
  appMode: (() => {
    try {
      return localStorage.getItem("kendr:appMode") || "studio";
    } catch {
      return "studio";
    }
  })(),
  selectedModel: (() => {
    try {
      return localStorage.getItem("kendr:selectedModel") || null;
    } catch {
      return null;
    }
  })(),
  // Views & panels
  activeView: "studio",
  sidebarOpen: true,
  chatOpen: true,
  terminalOpen: false,
  // Editor tabs
  openTabs: [],
  // [{path, name, language, modified}]
  activeTabPath: null,
  // Project
  projectRoot: "",
  // Backend services (gateway :8790 + UI :2151)
  backendStatus: "connecting",
  // legacy derived field used by other components
  backendServices: { ui: "connecting", gateway: "connecting", pid: null, kendrRoot: null, error: null },
  backendUrl: "http://127.0.0.1:2151",
  gatewayUrl: "http://127.0.0.1:8790",
  // Chat
  messages: [],
  // [{id, role, content, status, runId, agents}]
  activeRunId: null,
  streaming: false,
  // Runs
  runs: [],
  activityFeed: [],
  // Git
  gitStatus: null,
  gitBranch: "main",
  // Command palette
  commandPaletteOpen: false,
  // Settings (loaded from electron-store)
  settings: {},
  updateStatus: {
    supported: false,
    enabled: true,
    configured: false,
    invalidFeedUrl: false,
    status: "idle",
    currentVersion: null,
    availableVersion: null,
    downloadedVersion: null,
    checkedAt: null,
    progress: null,
    channel: "latest",
    feedUrl: "",
    feedSource: "none",
    autoDownload: true,
    autoInstallOnQuit: true,
    allowPrerelease: false,
    intervalMinutes: 240,
    error: null,
    message: ""
  },
  // Shared model/provider inventory cache
  modelInventory: null,
  modelInventoryLoading: false,
  modelInventoryError: false,
  modelInventoryFetchedAt: 0,
  ollamaModels: [],
  ollamaLoading: false,
  ollamaError: false,
  ollamaFetchedAt: 0,
  // Project mode
  editorSelection: null,
  // {path, text, startLine, startCol, endLine, endCol}
  terminalCmd: null,
  // {id, command, cwd} — consumed by TerminalPanel
  composerOpen: true
  // AI Composer visibility in project mode
};
function reducer(state, action) {
  switch (action.type) {
    case "SET_VIEW":
      return { ...state, activeView: normalizeView(action.view) };
    case "TOGGLE_SIDEBAR":
      return { ...state, sidebarOpen: !state.sidebarOpen };
    case "SET_SIDEBAR":
      return { ...state, sidebarOpen: action.open };
    case "TOGGLE_CHAT":
      return { ...state, chatOpen: !state.chatOpen };
    case "TOGGLE_TERMINAL":
      return { ...state, terminalOpen: !state.terminalOpen };
    case "SET_TERMINAL":
      return { ...state, terminalOpen: action.open };
    case "OPEN_TAB": {
      const exists = state.openTabs.find((t2) => t2.path === action.tab.path);
      if (exists) return { ...state, activeTabPath: action.tab.path };
      return {
        ...state,
        openTabs: [...state.openTabs, action.tab],
        activeTabPath: action.tab.path
      };
    }
    case "CLOSE_TAB": {
      const tabs = state.openTabs.filter((t2) => t2.path !== action.path);
      let active = state.activeTabPath;
      if (active === action.path) {
        const idx = state.openTabs.findIndex((t2) => t2.path === action.path);
        active = tabs[Math.min(idx, tabs.length - 1)]?.path || null;
      }
      return { ...state, openTabs: tabs, activeTabPath: active };
    }
    case "SET_ACTIVE_TAB":
      return { ...state, activeTabPath: action.path };
    case "MARK_TAB_MODIFIED": {
      const tabs = state.openTabs.map(
        (t2) => t2.path === action.path ? { ...t2, modified: action.modified } : t2
      );
      return { ...state, openTabs: tabs };
    }
    case "SET_PROJECT_ROOT":
      return { ...state, projectRoot: action.root };
    case "SET_BACKEND_STATUS":
      return { ...state, backendStatus: action.status };
    case "SET_BACKEND_URL":
      return { ...state, backendUrl: action.url };
    case "SET_BACKEND_SERVICES": {
      const svcs = { ...state.backendServices, ...action.services };
      const derived = svcs.ui === "running" && svcs.gateway === "running" ? "running" : svcs.ui === "starting" || svcs.gateway === "starting" ? "starting" : svcs.ui === "error" || svcs.gateway === "error" ? "error" : "stopped";
      return { ...state, backendServices: svcs, backendStatus: derived };
    }
    case "ADD_MESSAGE":
      return { ...state, messages: [...state.messages, action.message] };
    case "UPDATE_MESSAGE":
      return {
        ...state,
        messages: state.messages.map((m2) => m2.id === action.id ? { ...m2, ...action.updates } : m2)
      };
    case "SET_MESSAGES":
      return { ...state, messages: action.messages };
    case "CLEAR_MESSAGES":
      return { ...state, messages: [] };
    case "SET_STREAMING":
      return { ...state, streaming: action.streaming };
    case "SET_ACTIVE_RUN":
      return { ...state, activeRunId: action.runId };
    case "SET_RUNS":
      return { ...state, runs: action.runs };
    case "UPSERT_ACTIVITY_ENTRY": {
      const entry = action.entry;
      if (!entry?.id) return state;
      const existing = state.activityFeed.filter((item) => item.id !== entry.id);
      return {
        ...state,
        activityFeed: [entry, ...existing].slice(0, 40)
      };
    }
    case "REMOVE_ACTIVITY_ENTRIES": {
      const ids = new Set(Array.isArray(action.ids) ? action.ids : []);
      if (!ids.size) return state;
      return {
        ...state,
        activityFeed: state.activityFeed.filter((item) => !ids.has(item.id))
      };
    }
    case "CLEAR_ACTIVITY_FEED":
      return { ...state, activityFeed: [] };
    case "SET_GIT_STATUS":
      return { ...state, gitStatus: action.status, gitBranch: action.branch || state.gitBranch };
    case "TOGGLE_COMMAND_PALETTE":
      return { ...state, commandPaletteOpen: !state.commandPaletteOpen };
    case "SET_COMMAND_PALETTE":
      return { ...state, commandPaletteOpen: action.open };
    case "SET_SETTINGS":
      return { ...state, settings: { ...state.settings, ...action.settings } };
    case "SET_UPDATE_STATUS":
      return { ...state, updateStatus: { ...state.updateStatus, ...action.status } };
    case "SET_MODEL_INVENTORY_LOADING":
      return { ...state, modelInventoryLoading: action.loading, modelInventoryError: action.loading ? false : state.modelInventoryError };
    case "SET_MODEL_INVENTORY":
      return {
        ...state,
        modelInventory: action.inventory,
        modelInventoryLoading: false,
        modelInventoryError: false,
        modelInventoryFetchedAt: action.fetchedAt || Date.now()
      };
    case "SET_MODEL_INVENTORY_ERROR":
      return { ...state, modelInventoryLoading: false, modelInventoryError: true, modelInventoryFetchedAt: action.fetchedAt || state.modelInventoryFetchedAt };
    case "SET_OLLAMA_LOADING":
      return { ...state, ollamaLoading: action.loading, ollamaError: action.loading ? false : state.ollamaError };
    case "SET_OLLAMA_MODELS":
      return {
        ...state,
        ollamaModels: Array.isArray(action.models) ? action.models : [],
        ollamaLoading: false,
        ollamaError: false,
        ollamaFetchedAt: action.fetchedAt || Date.now()
      };
    case "SET_OLLAMA_ERROR":
      return { ...state, ollamaLoading: false, ollamaError: true, ollamaFetchedAt: action.fetchedAt || state.ollamaFetchedAt };
    case "SET_EDITOR_SELECTION":
      return { ...state, editorSelection: action.selection };
    case "RUN_COMMAND":
      return { ...state, terminalOpen: true, terminalCmd: { id: Date.now(), ...action.cmd } };
    case "CLEAR_TERMINAL_CMD":
      return { ...state, terminalCmd: null };
    case "TOGGLE_COMPOSER":
      return { ...state, composerOpen: !state.composerOpen };
    case "SET_APP_MODE": {
      try {
        localStorage.setItem("kendr:appMode", action.mode);
      } catch {
      }
      return { ...state, appMode: action.mode };
    }
    case "SET_MODEL": {
      try {
        if (action.model) localStorage.setItem("kendr:selectedModel", action.model);
        else localStorage.removeItem("kendr:selectedModel");
      } catch {
      }
      return { ...state, selectedModel: action.model };
    }
    default:
      return state;
  }
}
function AppProvider({ children }) {
  const [state, dispatch] = reactExports.useReducer(reducer, initialState);
  reactExports.useEffect(() => {
    const api = window.kendrAPI;
    if (!api) return;
    api.settings.getAll().then((settings) => {
      dispatch({ type: "SET_SETTINGS", settings });
      if (settings.backendUrl) dispatch({ type: "SET_BACKEND_URL", url: settings.backendUrl });
      if (settings.projectRoot) dispatch({ type: "SET_PROJECT_ROOT", root: settings.projectRoot });
    });
  }, []);
  const refreshModelInventory = reactExports.useCallback(async (force = false) => {
    const backendReady = state.backendStatus === "running" || state.backendStatus === "connecting";
    if (!backendReady) return null;
    const isFresh = state.modelInventory && Date.now() - state.modelInventoryFetchedAt < MODEL_INVENTORY_TTL_MS;
    if (!force && (state.modelInventoryLoading || isFresh)) return state.modelInventory;
    dispatch({ type: "SET_MODEL_INVENTORY_LOADING", loading: true });
    try {
      const resp = await fetch(`${state.backendUrl || "http://127.0.0.1:2151"}/api/models`);
      if (!resp.ok) throw new Error(`inventory_${resp.status}`);
      const data = await resp.json();
      dispatch({ type: "SET_MODEL_INVENTORY", inventory: data || null, fetchedAt: Date.now() });
      return data || null;
    } catch (_2) {
      dispatch({ type: "SET_MODEL_INVENTORY_ERROR", fetchedAt: Date.now() });
      return null;
    }
  }, [state.backendStatus, state.backendUrl, state.modelInventory, state.modelInventoryFetchedAt, state.modelInventoryLoading]);
  const refreshOllamaModels = reactExports.useCallback(async (force = false) => {
    const backendReady = state.backendStatus === "running" || state.backendStatus === "connecting";
    if (!backendReady) return [];
    const isFresh = Array.isArray(state.ollamaModels) && state.ollamaFetchedAt && Date.now() - state.ollamaFetchedAt < OLLAMA_MODELS_TTL_MS;
    if (!force && (state.ollamaLoading || isFresh)) return state.ollamaModels;
    dispatch({ type: "SET_OLLAMA_LOADING", loading: true });
    try {
      const resp = await fetch(`${state.backendUrl || "http://127.0.0.1:2151"}/api/models/ollama`);
      if (!resp.ok) throw new Error(`ollama_${resp.status}`);
      const data = await resp.json();
      const models = Array.isArray(data.models) ? data.models : [];
      dispatch({ type: "SET_OLLAMA_MODELS", models, fetchedAt: Date.now() });
      return models;
    } catch (_2) {
      dispatch({ type: "SET_OLLAMA_ERROR", fetchedAt: Date.now() });
      return [];
    }
  }, [state.backendStatus, state.backendUrl, state.ollamaFetchedAt, state.ollamaLoading, state.ollamaModels]);
  const refreshModelData = reactExports.useCallback(async (force = false) => {
    await Promise.all([refreshModelInventory(force), refreshOllamaModels(force)]);
  }, [refreshModelInventory, refreshOllamaModels]);
  const modelsFetchedRef = React.useRef(false);
  reactExports.useEffect(() => {
    if (state.backendStatus !== "running" && state.backendStatus !== "connecting") return;
    if (modelsFetchedRef.current) return;
    modelsFetchedRef.current = true;
    refreshModelData(false);
  }, [refreshModelData, state.backendStatus]);
  reactExports.useEffect(() => {
    const api = window.kendrAPI;
    if (!api) return;
    api.backend.status().then((status) => {
      dispatch({ type: "SET_BACKEND_SERVICES", services: status });
    });
    const unsub = api.backend.onStatusChange((status) => {
      dispatch({ type: "SET_BACKEND_SERVICES", services: status });
    });
    return () => {
      try {
        unsub?.();
      } catch (_2) {
      }
    };
  }, []);
  reactExports.useEffect(() => {
    const api = window.kendrAPI;
    if (!api?.updates) return;
    api.updates.status().then((status) => {
      if (status) dispatch({ type: "SET_UPDATE_STATUS", status });
    });
    const unsub = api.updates.onStatusChange((status) => {
      dispatch({ type: "SET_UPDATE_STATUS", status });
    });
    return () => {
      try {
        unsub?.();
      } catch (_2) {
      }
    };
  }, []);
  reactExports.useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "P") {
        e.preventDefault();
        dispatch({ type: "TOGGLE_COMMAND_PALETTE" });
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "`") {
        e.preventDefault();
        dispatch({ type: "TOGGLE_TERMINAL" });
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "b") {
        e.preventDefault();
        dispatch({ type: "TOGGLE_SIDEBAR" });
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "J") {
        e.preventDefault();
        dispatch({ type: "SET_VIEW", view: "developer" });
      }
      if (e.key === "Escape") {
        dispatch({ type: "SET_COMMAND_PALETTE", open: false });
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const openFile = reactExports.useCallback(async (filePath) => {
    const api = window.kendrAPI;
    if (!api) return;
    const ext = filePath.split(".").pop()?.toLowerCase() || "";
    const langMap = {
      js: "javascript",
      jsx: "javascript",
      ts: "typescript",
      tsx: "typescript",
      py: "python",
      json: "json",
      md: "markdown",
      html: "html",
      css: "css",
      yml: "yaml",
      yaml: "yaml",
      sh: "shell",
      bash: "shell",
      txt: "plaintext",
      rs: "rust",
      go: "go",
      java: "java",
      cpp: "cpp",
      c: "c",
      rb: "ruby",
      php: "php",
      swift: "swift",
      kt: "kotlin",
      sql: "sql",
      xml: "xml",
      toml: "toml",
      ini: "ini",
      env: "plaintext",
      dockerfile: "dockerfile"
    };
    const language = langMap[ext] || "plaintext";
    const { content, error } = await api.fs.readFile(filePath);
    if (error) return;
    const name = filePath.split(/[\\/]/).pop();
    dispatch({ type: "OPEN_TAB", tab: { path: filePath, name, language, content, modified: false } });
  }, []);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(AppContext.Provider, { value: { state, dispatch, openFile, refreshModelInventory, refreshOllamaModels, refreshModelData }, children });
}
function useApp() {
  const ctx = reactExports.useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
const DOT = { running: "●", starting: "◌", error: "✕", stopped: "○", connecting: "◌" };
const CLS = { running: "svc-ok", starting: "svc-warn", error: "svc-error", stopped: "svc-muted", connecting: "svc-warn" };
function StatusBar() {
  const { state, dispatch } = useApp();
  const [time, setTime] = reactExports.useState(/* @__PURE__ */ new Date());
  const api = window.kendrAPI;
  reactExports.useEffect(() => {
    const id2 = setInterval(() => setTime(/* @__PURE__ */ new Date()), 3e4);
    return () => clearInterval(id2);
  }, []);
  const { ui: ui2, gateway, pid, error } = state.backendServices;
  const activeTab = state.openTabs.find((t2) => t2.path === state.activeTabPath);
  const activeRunId = String(state.activeRunId || "").trim();
  const runLabel = activeRunId ? activeRunId.slice(-8) : "";
  const handleServiceClick = async () => {
    if (ui2 === "running" && gateway === "running") return;
    if (ui2 === "stopped" || gateway === "stopped" || ui2 === "error" || gateway === "error") {
      await api?.backend.start();
    }
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-bar", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-bar-left", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs(
        "button",
        {
          className: "status-item status-services",
          title: error ? `Error: ${error}` : `Gateway: ${gateway}  |  UI: ${ui2}${pid ? `  |  PID ${pid}` : ""}
Click to start if stopped`,
          onClick: handleServiceClick,
          children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: `svc-dot ${CLS[gateway] || "svc-muted"}`, title: `Gateway :8790 — ${gateway}`, children: [
              DOT[gateway] || "○",
              " GW"
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "svc-sep", children: "·" }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: `svc-dot ${CLS[ui2] || "svc-muted"}`, title: `UI :2151 — ${ui2}`, children: [
              DOT[ui2] || "○",
              " UI"
            ] })
          ]
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "status-item status-branch", title: `Branch: ${state.gitBranch}`, children: [
        "⎇ ",
        state.gitBranch
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-bar-center", children: [
      activeRunId && /* @__PURE__ */ jsxRuntimeExports.jsxs(
        "button",
        {
          className: "status-item status-bg-run",
          title: `Background run active (${activeRunId}). Click to open Studio.`,
          onClick: () => dispatch({ type: "SET_VIEW", view: "studio" }),
          children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pulse-dot" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Background run" }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "status-bg-run-id", children: [
              "#",
              runLabel
            ] })
          ]
        }
      ),
      state.streaming && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "status-item status-streaming", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pulse-dot" }),
        " Agent running…"
      ] }),
      (ui2 === "starting" || gateway === "starting") && !state.streaming && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "status-item status-starting", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pulse-dot" }),
        " Starting services…"
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-bar-right", children: [
      activeTab && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-item", children: activeTab.language || "plain" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-divider" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-item", children: time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: "status-item status-btn",
          title: "Toggle Terminal (Ctrl+`)",
          onClick: () => dispatch({ type: "TOGGLE_TERMINAL" }),
          children: "⌨"
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: "status-item status-btn",
          title: "Command Palette (Ctrl+Shift+P)",
          onClick: () => dispatch({ type: "TOGGLE_COMMAND_PALETTE" }),
          children: "⌘"
        }
      )
    ] })
  ] });
}
const COMMANDS = [
  { id: "toggle-terminal", label: "Toggle Terminal", keys: "Ctrl+`" },
  { id: "toggle-sidebar", label: "Toggle Sidebar", keys: "Ctrl+B" },
  { id: "toggle-chat", label: "Toggle Chat Panel", keys: "" },
  { id: "view-home", label: "View: Home", keys: "" },
  { id: "view-studio", label: "View: Studio", keys: "" },
  { id: "view-build", label: "View: Build", keys: "" },
  { id: "view-integrations", label: "View: Integrations", keys: "" },
  { id: "view-runs", label: "View: Runs", keys: "" },
  { id: "view-settings", label: "View: Settings", keys: "" },
  { id: "view-developer", label: "View: Developer Workspace", keys: "" },
  { id: "view-about", label: "View: About Kendr", keys: "" },
  { id: "open-folder", label: "Open Folder…", keys: "" },
  { id: "start-backend", label: "Backend: Start", keys: "" },
  { id: "restart-backend", label: "Backend: Restart", keys: "" },
  { id: "stop-backend", label: "Backend: Stop", keys: "" },
  { id: "new-chat", label: "Chat: New Conversation", keys: "" },
  { id: "clear-chat", label: "Chat: Clear Messages", keys: "" }
];
function CommandPalette() {
  const { state, dispatch, openFile } = useApp();
  const [query, setQuery] = reactExports.useState("");
  const [selected, setSelected] = reactExports.useState(0);
  const inputRef = reactExports.useRef(null);
  const api = window.kendrAPI;
  reactExports.useEffect(() => {
    inputRef.current?.focus();
  }, []);
  const filtered = COMMANDS.filter(
    (c) => c.label.toLowerCase().includes(query.toLowerCase())
  );
  const run = async (cmd) => {
    dispatch({ type: "SET_COMMAND_PALETTE", open: false });
    switch (cmd.id) {
      case "toggle-terminal":
        dispatch({ type: "TOGGLE_TERMINAL" });
        break;
      case "toggle-sidebar":
        dispatch({ type: "TOGGLE_SIDEBAR" });
        break;
      case "toggle-chat":
        dispatch({ type: "TOGGLE_CHAT" });
        break;
      case "view-home":
        dispatch({ type: "SET_VIEW", view: "home" });
        break;
      case "view-studio":
        dispatch({ type: "SET_VIEW", view: "studio" });
        break;
      case "view-build":
        dispatch({ type: "SET_VIEW", view: "build" });
        break;
      case "view-integrations":
        dispatch({ type: "SET_VIEW", view: "integrations" });
        break;
      case "view-runs":
        dispatch({ type: "SET_VIEW", view: "runs" });
        break;
      case "view-settings":
        dispatch({ type: "SET_VIEW", view: "settings" });
        break;
      case "view-developer":
        dispatch({ type: "SET_VIEW", view: "developer" });
        break;
      case "view-about":
        dispatch({ type: "SET_VIEW", view: "about" });
        break;
      case "open-folder": {
        const dir = await api?.dialog.openDirectory();
        if (dir) {
          dispatch({ type: "SET_PROJECT_ROOT", root: dir });
          await api?.settings.set("projectRoot", dir);
          dispatch({ type: "SET_VIEW", view: "developer" });
        }
        break;
      }
      case "start-backend":
        await api?.backend.start();
        break;
      case "restart-backend":
        await api?.backend.restart();
        break;
      case "stop-backend":
        await api?.backend.stop();
        break;
      case "new-chat":
        dispatch({ type: "SET_MESSAGES", messages: [] });
        break;
      case "clear-chat":
        dispatch({ type: "CLEAR_MESSAGES" });
        break;
    }
  };
  const handleKey = (e) => {
    if (e.key === "ArrowDown") setSelected((s) => Math.min(s + 1, filtered.length - 1));
    else if (e.key === "ArrowUp") setSelected((s) => Math.max(s - 1, 0));
    else if (e.key === "Enter" && filtered[selected]) run(filtered[selected]);
    else if (e.key === "Escape") dispatch({ type: "SET_COMMAND_PALETTE", open: false });
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "palette-backdrop", onClick: () => dispatch({ type: "SET_COMMAND_PALETTE", open: false }), children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "palette", onClick: (e) => e.stopPropagation(), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "input",
      {
        ref: inputRef,
        className: "palette-input",
        placeholder: "Type a command…",
        value: query,
        onChange: (e) => {
          setQuery(e.target.value);
          setSelected(0);
        },
        onKeyDown: handleKey
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "palette-list", children: [
      filtered.length === 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "palette-empty", children: "No commands match" }),
      filtered.map((cmd, i) => /* @__PURE__ */ jsxRuntimeExports.jsxs(
        "div",
        {
          className: `palette-item ${i === selected ? "palette-item--selected" : ""}`,
          onClick: () => run(cmd),
          onMouseEnter: () => setSelected(i),
          children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "palette-item-label", children: cmd.label }),
            cmd.keys && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "palette-item-keys", children: cmd.keys })
          ]
        },
        cmd.id
      ))
    ] })
  ] }) });
}
function useMenuDefs() {
  const { state, dispatch, openFile } = useApp();
  const api = window.kendrAPI;
  const newFile = async () => {
    const path = await api?.dialog.saveFile("");
    if (path) {
      await api?.fs.createFile(path);
      openFile(path);
    }
  };
  const openFolder = async () => {
    const dir = await api?.dialog.openDirectory();
    if (dir) dispatch({ type: "SET_PROJECT_ROOT", root: dir });
  };
  const openFileDialog = async () => {
    const path = await api?.dialog.openFile();
    if (path) openFile(path);
  };
  const saveActive = () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "s", ctrlKey: true, bubbles: true }));
  const closeTab = () => {
    if (state.activeTabPath) dispatch({ type: "CLOSE_TAB", path: state.activeTabPath });
  };
  return [
    {
      label: "File",
      items: [
        { label: "New File", shortcut: "Ctrl+N", action: newFile },
        { label: "Open File…", shortcut: "Ctrl+O", action: openFileDialog },
        { label: "Open Folder…", shortcut: "Ctrl+Shift+O", action: openFolder },
        { sep: true },
        { label: "Save", shortcut: "Ctrl+S", action: saveActive },
        { label: "Close Tab", shortcut: "Ctrl+W", action: closeTab },
        { sep: true },
        { label: "Settings", shortcut: "Ctrl+,", action: () => {
          dispatch({ type: "SET_VIEW", view: "settings" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { sep: true },
        { label: "Quit", shortcut: "Alt+F4", action: () => api?.window.close() }
      ]
    },
    {
      label: "Edit",
      items: [
        { label: "Undo", shortcut: "Ctrl+Z", action: () => document.execCommand("undo") },
        { label: "Redo", shortcut: "Ctrl+Y", action: () => document.execCommand("redo") },
        { sep: true },
        { label: "Cut", shortcut: "Ctrl+X", action: () => document.execCommand("cut") },
        { label: "Copy", shortcut: "Ctrl+C", action: () => document.execCommand("copy") },
        { label: "Paste", shortcut: "Ctrl+V", action: () => document.execCommand("paste") },
        { sep: true },
        { label: "Find", shortcut: "Ctrl+F", action: () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "f", ctrlKey: true, bubbles: true })) },
        { label: "Replace", shortcut: "Ctrl+H", action: () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "h", ctrlKey: true, bubbles: true })) }
      ]
    },
    {
      label: "View",
      items: [
        { label: "Build Workspace", shortcut: "Ctrl+Shift+J", action: () => dispatch({ type: "SET_VIEW", view: "developer" }) },
        { sep: true },
        { label: "Studio", action: () => {
          dispatch({ type: "SET_VIEW", view: "studio" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { label: "Build Workspace", action: () => {
          dispatch({ type: "SET_VIEW", view: "developer" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { label: "Automation & Builders", action: () => {
          dispatch({ type: "SET_VIEW", view: "build" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { label: "Machine", action: () => {
          dispatch({ type: "SET_VIEW", view: "machine" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { label: "Memory", action: () => {
          dispatch({ type: "SET_VIEW", view: "memory" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { label: "Integrations", action: () => {
          dispatch({ type: "SET_VIEW", view: "integrations" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { label: "Runs", action: () => {
          dispatch({ type: "SET_VIEW", view: "runs" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { label: "Marketplace", action: () => {
          dispatch({ type: "SET_VIEW", view: "marketplace" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { label: "Settings", action: () => {
          dispatch({ type: "SET_VIEW", view: "settings" });
          dispatch({ type: "SET_SIDEBAR", open: true });
        } },
        { sep: true },
        { label: state.chatOpen ? "Hide Chat" : "Show Chat", shortcut: "Ctrl+Shift+C", action: () => dispatch({ type: "TOGGLE_CHAT" }) },
        { label: "Toggle Sidebar", shortcut: "Ctrl+B", action: () => dispatch({ type: "TOGGLE_SIDEBAR" }) },
        { sep: true },
        { label: "Command Palette", shortcut: "Ctrl+Shift+P", action: () => dispatch({ type: "TOGGLE_COMMAND_PALETTE" }) }
      ]
    },
    {
      label: "Terminal",
      items: [
        { label: "New Terminal", shortcut: "Ctrl+`", action: () => dispatch({ type: "SET_TERMINAL", open: true }) },
        { label: "Toggle Terminal", shortcut: "Ctrl+`", action: () => dispatch({ type: "TOGGLE_TERMINAL" }) },
        { sep: true },
        { label: "Run: npm dev", action: () => sendToTerminal("npm run dev") },
        { label: "Run: npm test", action: () => sendToTerminal("npm test") },
        { label: "Run: npm build", action: () => sendToTerminal("npm run build") },
        { label: "Run: python main.py", action: () => sendToTerminal("python main.py") },
        { label: "Run: pytest", action: () => sendToTerminal("pytest") }
      ]
    },
    {
      label: "Run",
      items: [
        { label: "Open Run Panel", action: () => window.dispatchEvent(new CustomEvent("kendr:open-run-panel")) },
        { sep: true },
        { label: "Start Backend", action: () => api?.backend.start() },
        { label: "Stop Backend", action: () => api?.backend.stop() },
        { label: "Restart Backend", action: () => api?.backend.restart() },
        { sep: true },
        { label: "Backend Logs", action: async () => {
          const logs = await api?.backend.getLogs();
          window.dispatchEvent(new CustomEvent("kendr:show-logs", { detail: logs }));
        } }
      ]
    },
    {
      label: "Extensions",
      items: [
        { label: "Build", action: () => dispatch({ type: "SET_VIEW", view: "build" }) },
        { label: "Integrations", action: () => dispatch({ type: "SET_VIEW", view: "integrations" }) },
        { label: "Marketplace", action: () => dispatch({ type: "SET_VIEW", view: "marketplace" }) },
        { sep: true },
        { label: "Add MCP Server", action: () => {
          dispatch({ type: "SET_VIEW", view: "integrations" });
          setTimeout(() => window.dispatchEvent(new CustomEvent("kendr:mcp-add")), 150);
        } },
        { label: "Discover MCP Tools", action: () => {
          dispatch({ type: "SET_VIEW", view: "integrations" });
          setTimeout(() => window.dispatchEvent(new CustomEvent("kendr:mcp-discover-all")), 150);
        } },
        { sep: true },
        { label: "Browse Skill Intents", action: () => dispatch({ type: "SET_VIEW", view: "marketplace" }) },
        { label: "Reload Capabilities", action: async () => {
          try {
            const base = state.backendUrl || "http://127.0.0.1:2151";
            await fetch(`${base}/api/capabilities/reload`, { method: "POST" });
          } catch {
          }
        } }
      ]
    },
    {
      label: "Help",
      items: [
        { label: "Keyboard Shortcuts", shortcut: "Ctrl+Shift+P", action: () => dispatch({ type: "TOGGLE_COMMAND_PALETTE" }) },
        { label: "Model Docs", action: () => dispatch({ type: "SET_VIEW", view: "settings" }) },
        { sep: true },
        { label: "About Kendr", action: () => dispatch({ type: "SET_VIEW", view: "about" }) }
      ]
    }
  ];
}
function sendToTerminal(command) {
  window.dispatchEvent(new CustomEvent("kendr:run-command", { detail: { command } }));
  window.dispatchEvent(new CustomEvent("kendr:open-terminal"));
}
function MenuBar() {
  const [open, setOpen] = reactExports.useState(null);
  const [hovered, setHovered] = reactExports.useState(null);
  const barRef = reactExports.useRef(null);
  const menuDefs = useMenuDefs();
  reactExports.useEffect(() => {
    if (open === null) return;
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(null);
    };
    const onMouse = (e) => {
      if (barRef.current && !barRef.current.contains(e.target)) setOpen(null);
    };
    document.addEventListener("mousedown", onMouse);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouse);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const toggle = (i) => setOpen((o) => o === i ? null : i);
  const hoverOpen = (i) => {
    if (open !== null) setOpen(i);
  };
  const exec = (action) => {
    setOpen(null);
    setHovered(null);
    action?.();
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "menubar", ref: barRef, style: { WebkitAppRegion: "no-drag" }, children: menuDefs.map((menu, i) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "menubar-item", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        className: `menubar-btn ${open === i ? "active" : ""}`,
        onMouseDown: () => toggle(i),
        onMouseEnter: () => hoverOpen(i),
        children: menu.label
      }
    ),
    open === i && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "menubar-dropdown", children: menu.items.map(
      (item, j) => item.sep ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "menubar-sep" }, `sep-${j}`) : /* @__PURE__ */ jsxRuntimeExports.jsxs(
        "button",
        {
          className: `menubar-row ${hovered === `${i}-${j}` ? "hovered" : ""}`,
          onMouseEnter: () => setHovered(`${i}-${j}`),
          onMouseLeave: () => setHovered(null),
          onMouseDown: () => exec(item.action),
          disabled: !item.action,
          children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "menubar-row-label", children: item.label }),
            item.shortcut && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "menubar-row-shortcut", children: item.shortcut })
          ]
        },
        item.label
      )
    ) })
  ] }, menu.label)) });
}
function formatErrorMessage(error) {
  if (!error) return "Unknown renderer failure.";
  const message = String(error?.message || error || "").trim();
  return message || "Unknown renderer failure.";
}
class RendererErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    this.setState({ error, info });
    try {
      console.error("RendererErrorBoundary caught an error", error, info);
    } catch (_2) {
    }
  }
  handleReload = () => {
    try {
      window.location.reload();
    } catch (_2) {
    }
  };
  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;
    const detail = String(info?.componentStack || "").trim();
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        style: {
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: 24,
          background: "radial-gradient(circle at top, rgba(232, 117, 88, 0.14), transparent 42%), #0d0f14",
          color: "#f3f4f6"
        },
        children: /* @__PURE__ */ jsxRuntimeExports.jsxs(
          "div",
          {
            style: {
              width: "min(760px, 100%)",
              borderRadius: 20,
              border: "1px solid rgba(255,255,255,0.12)",
              background: "rgba(15, 23, 42, 0.88)",
              boxShadow: "0 18px 48px rgba(0,0,0,0.32)",
              padding: 24
            },
            children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", color: "#fca5a5", marginBottom: 10 }, children: "Renderer Recovery" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 28, fontWeight: 700, marginBottom: 12 }, children: "Kendr hit a renderer error." }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 15, lineHeight: 1.6, color: "#cbd5e1", marginBottom: 18 }, children: "The app stayed open instead of falling through to a blank screen. Reload the window and try the same action again." }),
              /* @__PURE__ */ jsxRuntimeExports.jsxs(
                "div",
                {
                  style: {
                    borderRadius: 14,
                    border: "1px solid rgba(252, 165, 165, 0.26)",
                    background: "rgba(127, 29, 29, 0.22)",
                    padding: 14,
                    marginBottom: 18,
                    fontFamily: "'Cascadia Code', 'Fira Code', monospace",
                    fontSize: 13,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word"
                  },
                  children: [
                    formatErrorMessage(error),
                    detail ? `

${detail}` : ""
                  ]
                }
              ),
              /* @__PURE__ */ jsxRuntimeExports.jsx(
                "button",
                {
                  type: "button",
                  onClick: this.handleReload,
                  style: {
                    border: "none",
                    borderRadius: 10,
                    background: "#f97316",
                    color: "#111827",
                    fontWeight: 700,
                    padding: "11px 16px",
                    cursor: "pointer"
                  },
                  children: "Reload Kendr"
                }
              )
            ]
          }
        )
      }
    );
  }
}
function basename$2(filePath) {
  return String(filePath || "").split(/[\\/]/).pop() || filePath || "file";
}
function parentDir(filePath) {
  const raw = String(filePath || "").trim();
  if (!raw) return "";
  const idx = Math.max(raw.lastIndexOf("/"), raw.lastIndexOf("\\"));
  if (idx <= 0) return raw;
  return raw.slice(0, idx);
}
function classifyDiffLine(line) {
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("diff --git") || line.startsWith("index ") || line.startsWith("---") || line.startsWith("+++")) return "meta";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "remove";
  return "context";
}
function countDiffLines(diffText) {
  let adds = 0;
  let removes = 0;
  for (const line of String(diffText || "").split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) adds += 1;
    if (line.startsWith("-")) removes += 1;
  }
  return { adds, removes };
}
function GitDiffPreview({ cwd, filePath, onClose, onOpenFile }) {
  const [loading, setLoading] = reactExports.useState(false);
  const [diff, setDiff] = reactExports.useState("");
  const [error, setError] = reactExports.useState("");
  const targetCwd = reactExports.useMemo(() => String(cwd || "").trim() || parentDir(filePath), [cwd, filePath]);
  const stats = reactExports.useMemo(() => countDiffLines(diff), [diff]);
  reactExports.useEffect(() => {
    if (!filePath) return void 0;
    let cancelled = false;
    async function loadDiff() {
      if (!targetCwd || !window.kendrAPI?.git?.diff) {
        setDiff("");
        setError("No git workspace available for diff preview.");
        setLoading(false);
        return;
      }
      setLoading(true);
      setDiff("");
      setError("");
      try {
        const result = await window.kendrAPI.git.diff(targetCwd, filePath);
        if (cancelled) return;
        if (result?.error) {
          setError(String(result.error));
          setDiff("");
        } else {
          setDiff(String(result?.diff || ""));
        }
      } catch (err) {
        if (cancelled) return;
        setError(String(err?.message || err || "Failed to load diff preview."));
        setDiff("");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadDiff();
    return () => {
      cancelled = true;
    };
  }, [filePath, targetCwd]);
  if (!filePath) return null;
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "gdp-overlay", onClick: (event) => {
    if (event.target === event.currentTarget) onClose?.();
  }, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "gdp-sheet", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "gdp-header", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "gdp-header-main", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "gdp-eyebrow", children: "Diff Preview" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "gdp-title", children: basename$2(filePath) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "gdp-path", children: filePath })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "gdp-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "gdp-btn", onClick: () => onOpenFile?.(filePath), children: "Open file" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "gdp-btn gdp-btn--close", onClick: () => onClose?.(), children: "Close" })
      ] })
    ] }),
    !!diff && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "gdp-stats", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "gdp-stat gdp-stat--add", children: [
        "+",
        stats.adds
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "gdp-stat gdp-stat--remove", children: [
        "-",
        stats.removes
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "gdp-body", children: loading ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "gdp-empty", children: "Loading diff…" }) : error ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "gdp-empty gdp-empty--error", children: error }) : !diff ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "gdp-empty", children: "No git diff for this file." }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "gdp-code", children: diff.split("\n").map((line, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `gdp-line gdp-line--${classifyDiffLine(line)}`, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "gdp-line-no", children: index2 + 1 }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("code", { className: "gdp-line-text", children: line || " " })
    ] }, `${index2}-${line}`)) }) })
  ] }) });
}
function resolveSelectedModel(selectedModel) {
  const raw = String(selectedModel || "").trim();
  if (!raw) {
    return { raw: "", provider: "", model: "", isLocal: false, label: "Auto" };
  }
  const slash = raw.indexOf("/");
  if (slash === -1) {
    return {
      raw,
      provider: "",
      model: raw,
      isLocal: false,
      label: raw
    };
  }
  const provider = raw.slice(0, slash).trim().toLowerCase();
  const model = raw.slice(slash + 1).trim();
  const providerLabel = provider === "ollama" ? "Local" : provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : "Model";
  return {
    raw,
    provider,
    model,
    isLocal: provider === "ollama",
    label: `${providerLabel} · ${model || "default"}`
  };
}
const MODEL_CONTEXT_WINDOWS = [
  ["gpt-5.4", 4e5],
  ["gpt-5.3", 4e5],
  ["gpt-5.2", 4e5],
  ["gpt-5.1", 4e5],
  ["gpt-5-mini", 4e5],
  ["gpt-5-nano", 4e5],
  ["gpt-5", 4e5],
  ["gpt-4.1", 1047576],
  ["o4-mini", 2e5],
  ["o3", 2e5],
  ["o1", 2e5],
  ["gpt-4o", 128e3],
  ["gpt-4-turbo", 128e3],
  ["gpt-4", 8192],
  ["gpt-3.5", 16385],
  ["claude-sonnet-4", 2e5],
  ["claude-opus-4", 2e5],
  ["claude", 2e5],
  ["gemini-2.5-pro", 1048576],
  ["gemini-2.5-flash", 1048576],
  ["gemini-2.0-flash", 1048576],
  ["gemini-1.5-pro", 2097152],
  ["gemini-1.5-flash", 1048576],
  ["gemini", 1048576],
  ["grok-4.20", 2e6],
  ["grok-4", 2e6],
  ["grok", 131072],
  ["llama3", 131072],
  ["llama", 131072],
  ["mistral", 32768],
  ["phi", 131072],
  ["qwen", 131072],
  ["glm", 131072],
  ["minimax", 1e6]
];
function approximateContextWindow(model) {
  const normalized = String(model || "").trim().toLowerCase();
  if (!normalized) return 128e3;
  for (const [needle, limit] of MODEL_CONTEXT_WINDOWS) {
    if (normalized.includes(needle)) return limit;
  }
  return 128e3;
}
function resolveContextWindow(selectedModel, modelInventory) {
  const selected = resolveSelectedModel(selectedModel);
  const providers = Array.isArray(modelInventory?.providers) ? modelInventory.providers : [];
  if (selected.provider && selected.model) {
    const matched = providers.find((provider) => String(provider?.provider || "").trim().toLowerCase() === selected.provider && String(provider?.model || "").trim() === selected.model && Number(provider?.context_window || 0) > 0);
    if (matched) return Number(matched.context_window);
    return approximateContextWindow(selected.model);
  }
  return Number(modelInventory?.active_context_window || modelInventory?.context_window || 128e3) || 128e3;
}
function resolveAgentCapability(selectedModel, modelInventory) {
  const selected = resolveSelectedModel(selectedModel);
  if (!selected.provider || !selected.model) return true;
  const providers = Array.isArray(modelInventory?.providers) ? modelInventory.providers : [];
  const provider = providers.find((item) => String(item?.provider || "").trim().toLowerCase() === selected.provider);
  const details = Array.isArray(provider?.selectable_model_details) ? provider.selectable_model_details : [];
  const matched = details.find((item) => String(item?.name || "").trim() === selected.model);
  if (matched && typeof matched.agent_capable === "boolean") return matched.agent_capable;
  if (typeof provider?.agent_capable === "boolean" && String(provider?.model || "").trim() === selected.model) return provider.agent_capable;
  return selected.provider !== "ollama";
}
function basename$1(path) {
  return String(path || "").split(/[\\/]/).pop() || "";
}
function normalizeStageRow(stage) {
  if (!stage || typeof stage !== "object" || Array.isArray(stage)) return null;
  return {
    stage: String(stage.stage || "").trim(),
    label: String(stage.label || "").trim(),
    provider: String(stage.provider || "").trim(),
    model: String(stage.model || "").trim(),
    reason: String(stage.reason || "").trim()
  };
}
function normalizeStageCandidate(candidate) {
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return null;
  const provider = String(candidate.provider || "").trim();
  const model = String(candidate.model || "").trim();
  if (!provider || !model) return null;
  return {
    stage: String(candidate.stage || "").trim(),
    label: String(candidate.label || "").trim(),
    provider,
    model,
    value: `${provider}/${model}`,
    labelFull: String(candidate.label_full || "").trim(),
    reason: String(candidate.reason || "").trim(),
    costBand: String(candidate.cost_band || candidate.costBand || "unknown").trim() || "unknown",
    qualityScore: Number(candidate.quality_score || candidate.qualityScore || 0) || 0
  };
}
function normalizeWorkflowCombo(combo) {
  if (!combo || typeof combo !== "object" || Array.isArray(combo)) {
    return {
      available: false,
      summary: "",
      estimatedCostBand: "unknown",
      estimated_cost_band: "unknown",
      stages: []
    };
  }
  const estimatedCostBand = String(combo.estimated_cost_band || combo.estimatedCostBand || "unknown").trim() || "unknown";
  return {
    available: Boolean(combo.available),
    summary: String(combo.summary || "").trim(),
    estimatedCostBand,
    estimated_cost_band: estimatedCostBand,
    stages: Array.isArray(combo.stages) ? combo.stages.map(normalizeStageRow).filter(Boolean) : []
  };
}
function normalizeWorkflowStageOptions(stageOptions) {
  const raw = Array.isArray(stageOptions) ? stageOptions : [];
  return raw.map((stageOption) => {
    if (!stageOption || typeof stageOption !== "object" || Array.isArray(stageOption)) return null;
    return {
      stage: String(stageOption.stage || "").trim(),
      label: String(stageOption.label || "").trim(),
      candidates: Array.isArray(stageOption.candidates) ? stageOption.candidates.map(normalizeStageCandidate).filter(Boolean) : []
    };
  }).filter(Boolean);
}
function resolveWorkflowRecommendation(modelInventory, workflowId) {
  const normalizedId = String(workflowId).trim();
  if (!normalizedId) return null;
  const payload = modelInventory?.workflow_recommendations;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const workflowList = Array.isArray(payload.workflows) ? payload.workflows : payload.workflows && typeof payload.workflows === "object" && !Array.isArray(payload.workflows) ? Object.values(payload.workflows) : [];
  const directMatch = workflowList.find((item) => item && typeof item === "object" && !Array.isArray(item) && String(item.id || "").trim() === normalizedId);
  if (directMatch) return directMatch;
  const legacyEntry = payload[normalizedId];
  if (legacyEntry && typeof legacyEntry === "object" && !Array.isArray(legacyEntry)) {
    return {
      id: normalizedId,
      ...legacyEntry
    };
  }
  return null;
}
function basename(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const normalized = raw.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : normalized;
}
function pushUniqueLabel(list, value, limit = 4) {
  const next = String(value || "").trim();
  if (!next || list.some((item) => item.label === next) || list.length >= limit) return;
  list.push({ label: next, path: "" });
}
function pushUniqueItem(list, item, limit = 4) {
  const label = String(item?.label || "").trim();
  const path = String(item?.path || "").trim();
  if (!label || list.length >= limit) return;
  if (list.some((entry) => entry.label === label && String(entry.path || "").trim() === path)) return;
  list.push({
    label,
    path,
    name: String(item?.name || label).trim(),
    kind: String(item?.kind || "").trim(),
    ext: String(item?.ext || "").trim(),
    downloadUrl: String(item?.downloadUrl || "").trim(),
    viewUrl: String(item?.viewUrl || "").trim()
  });
}
function normalizeArtifactItem$1(artifact) {
  if (!artifact) return null;
  if (typeof artifact === "string") {
    const raw = artifact.trim();
    if (!raw) return null;
    return {
      label: basename(raw),
      name: basename(raw),
      path: raw,
      kind: "",
      ext: raw.includes(".") ? raw.split(".").pop().toLowerCase() : "",
      downloadUrl: "",
      viewUrl: ""
    };
  }
  if (typeof artifact !== "object") return null;
  const path = String(artifact.path || artifact.file_path || "").trim();
  const name = String(artifact.name || artifact.label || "").trim();
  const label = name || basename(path);
  if (!label) return null;
  const ext = String(artifact.ext || (label.includes(".") ? label.split(".").pop() : "")).trim().toLowerCase();
  return {
    label,
    name: label,
    path,
    kind: String(artifact.kind || "").trim().toLowerCase(),
    ext,
    downloadUrl: String(artifact.download_url || artifact.downloadUrl || "").trim(),
    viewUrl: String(artifact.view_url || artifact.viewUrl || "").trim()
  };
}
function extractFileRefs(text) {
  const raw = String(text || "");
  if (!raw) return [];
  const matches = raw.match(/(?:[A-Za-z]:)?[A-Za-z0-9._@\-\\/ ]+\.[A-Za-z0-9]{1,8}/g) || [];
  const files = [];
  for (const match of matches) {
    const rawMatch = match.replace(/^["'`]+|["'`.,:;!?]+$/g, "").trim();
    const cleaned = basename(rawMatch);
    if (!cleaned) continue;
    pushUniqueItem(files, {
      label: cleaned,
      path: /[\\/]/.test(rawMatch) || /^[A-Za-z]:/.test(rawMatch) ? rawMatch : ""
    }, 6);
  }
  return files;
}
function normalizeChecklistStatus$1(value) {
  const status = String(value || "").trim().toLowerCase();
  if (["completed", "done", "success", "ok"].includes(status)) return "completed";
  if (["running", "in_progress", "started", "active"].includes(status)) return "running";
  if (["awaiting_approval", "awaiting_input", "awaiting"].includes(status)) return "awaiting";
  if (["failed", "error"].includes(status)) return "failed";
  if (["blocked"].includes(status)) return "blocked";
  if (["skipped"].includes(status)) return "skipped";
  return status || "pending";
}
function extractChecklist$1(result) {
  if (!result || typeof result !== "object") return [];
  const shellSteps = Array.isArray(result.shell_plan_steps) ? result.shell_plan_steps : [];
  if (shellSteps.length) {
    return shellSteps.map((step, index2) => ({
      step: Number(step.step || index2 + 1),
      title: String(step.title || step.description || `Step ${index2 + 1}`).trim() || `Step ${index2 + 1}`,
      status: normalizeChecklistStatus$1(step.status || (step.done ? "completed" : "pending")),
      detail: String(step.detail || step.reason || "").trim(),
      command: String(step.command || "").trim(),
      stdout: String(step.stdout || "").trim(),
      stderr: String(step.stderr || "").trim(),
      reason: String(step.reason || "").trim(),
      optional: !!step.optional,
      done: !!step.done || ["completed", "skipped"].includes(normalizeChecklistStatus$1(step.status)),
      returnCode: step.return_code
    }));
  }
  const planSteps = Array.isArray(result.plan_steps) ? result.plan_steps : [];
  if (planSteps.length) {
    const activeIndex = Math.max(0, Number(result.plan_step_index || 0));
    return planSteps.map((step, index2) => {
      const rawStatus = normalizeChecklistStatus$1(step.status || "");
      const status = rawStatus || (index2 < activeIndex ? "completed" : index2 === activeIndex ? "running" : "pending");
      return {
        step: index2 + 1,
        title: String(step.title || step.name || step.description || `Step ${index2 + 1}`).trim() || `Step ${index2 + 1}`,
        status,
        detail: String(step.success_criteria || step.description || "").trim(),
        command: "",
        stdout: "",
        stderr: "",
        reason: String(step.reason || "").trim(),
        optional: false,
        done: ["completed", "skipped"].includes(status),
        returnCode: null
      };
    });
  }
  return [];
}
function isPlanApprovalScope(scope, kind = "", request = null) {
  const joined = [
    scope,
    kind,
    request?.title,
    request?.summary,
    request?.metadata?.approval_mode
  ].map((value) => String(value || "").toLowerCase()).join(" ");
  return /\bplan\b|project_blueprint|blueprint|deep_research_confirmation/.test(joined);
}
function isSkillApproval(kind = "", request = null) {
  const approvalMode = String(request?.metadata?.approval_mode || "").trim().toLowerCase();
  const joined = [kind, approvalMode, request?.title].map((value) => String(value || "").toLowerCase()).join(" ");
  return /\bskill_approval\b|skill permission/.test(joined) || approvalMode === "skill_permission_grant";
}
function shouldMirrorActivityMessage(msg) {
  if (!msg || msg.role !== "assistant") return false;
  return !!(String(msg.runId || "").trim() || Array.isArray(msg.progress) && msg.progress.length || Array.isArray(msg.checklist) && msg.checklist.length || Array.isArray(msg.steps) && msg.steps.length || Array.isArray(msg.artifacts) && msg.artifacts.length || ["thinking", "streaming", "awaiting", "done", "error"].includes(String(msg.status || "").trim().toLowerCase()));
}
function buildActivityEntry(msg, { id: id2, source = "studio" } = {}) {
  if (!msg || typeof msg !== "object") return null;
  return {
    id: String(id2 || msg.id || "").trim(),
    source,
    runId: String(msg.runId || "").trim(),
    mode: String(msg.mode || "").trim(),
    modeLabel: String(msg.modeLabel || "").trim(),
    status: String(msg.status || "").trim(),
    content: String(msg.content || "").trim(),
    progress: Array.isArray(msg.progress) ? msg.progress : [],
    checklist: Array.isArray(msg.checklist) ? msg.checklist : [],
    steps: Array.isArray(msg.steps) ? msg.steps : [],
    artifacts: Array.isArray(msg.artifacts) ? msg.artifacts : [],
    approvalRequest: msg.approvalRequest && typeof msg.approvalRequest === "object" ? msg.approvalRequest : null,
    approvalScope: String(msg.approvalScope || "").trim(),
    approvalKind: String(msg.approvalKind || "").trim(),
    approvalState: String(msg.approvalState || "").trim(),
    statusText: String(msg.statusText || "").trim(),
    ts: msg.ts || (/* @__PURE__ */ new Date()).toISOString(),
    runStartedAt: msg.runStartedAt || msg.ts || (/* @__PURE__ */ new Date()).toISOString(),
    updatedAt: (/* @__PURE__ */ new Date()).toISOString()
  };
}
function classifyRunActivityKind(item) {
  if (!item || typeof item !== "object") return "task";
  const kind = String(item.kind || "").toLowerCase();
  const title = String(item.title || "").toLowerCase();
  const detail = String(item.detail || "").toLowerCase();
  const text = `${kind} ${title} ${detail}`;
  if (String(item.command || "").trim()) return "command";
  if (kind.includes("command") || kind.includes("shell")) return "command";
  if (/\b(search|query|grep|ripgrep|find in files|look up|browse|web search)\b/.test(text)) return "search";
  if (/\b(read|open|inspect|scan|inventory|load file|review file|explore file)\b/.test(text)) return "read";
  if (/\b(edit|write|modify|patch|rewrite|update file|create file|save file|refactor)\b/.test(text)) return "edit";
  if (/\b(test|verify|review|check|lint)\b/.test(text)) return "review";
  return "task";
}
function summarizeRunArtifacts(progress = [], artifacts = []) {
  const counts = {
    search: 0,
    read: 0,
    edit: 0,
    artifact: 0,
    command: 0,
    review: 0
  };
  const samples = {
    search: [],
    read: [],
    edit: [],
    artifact: [],
    command: [],
    review: []
  };
  for (const item of Array.isArray(progress) ? progress : []) {
    const kind = classifyRunActivityKind(item);
    if (counts[kind] !== void 0) counts[kind] += 1;
    const candidates = [
      ...extractFileRefs(item.title),
      ...extractFileRefs(item.detail),
      ...extractFileRefs(item.command)
    ];
    for (const candidate of candidates) pushUniqueItem(samples[kind] || [], candidate);
    if (!(samples[kind] || []).length) {
      const fallback = String(item.detail || item.title || item.command || "").trim();
      if (fallback) pushUniqueLabel(samples[kind] || [], fallback, 3);
    }
  }
  const artifactList = [...Array.isArray(artifacts) ? artifacts : []].sort((left, right) => {
    const normalize = (item) => normalizeArtifactItem$1(item) || {};
    const priority = (item) => {
      const normalized = normalize(item);
      const name = String(normalized.name || normalized.label || "").toLowerCase();
      const ext = String(normalized.ext || "").toLowerCase();
      if (/^report\.(pdf|docx|html|md)$/.test(name)) {
        return { pdf: 0, docx: 1, html: 2, md: 3 }[ext] ?? 4;
      }
      return 10;
    };
    return priority(left) - priority(right);
  });
  const reportItems = [];
  for (const artifact of artifactList) {
    const normalized = normalizeArtifactItem$1(artifact);
    if (!normalized) continue;
    counts.artifact += 1;
    if (/^report\.(pdf|docx|html|md)$/i.test(String(normalized.name || normalized.label || ""))) {
      pushUniqueItem(reportItems, normalized, 6);
    } else {
      pushUniqueItem(samples.artifact, normalized, 6);
    }
  }
  const makeCard = (kind, title) => ({
    kind,
    title,
    items: samples[kind]
  });
  const cards = [];
  const nonReportArtifactCount = Math.max(0, counts.artifact - reportItems.length);
  if (reportItems.length > 0) {
    cards.push({
      kind: "artifact",
      title: "Report downloads",
      items: reportItems
    });
  }
  if (counts.search > 0) cards.push(makeCard("search", `Searched ${counts.search} source${counts.search === 1 ? "" : "s"}`));
  if (counts.read > 0) cards.push(makeCard("read", `Read ${counts.read} file${counts.read === 1 ? "" : "s"}`));
  if (counts.edit > 0) cards.push(makeCard("edit", `Changed ${counts.edit} file${counts.edit === 1 ? "" : "s"}`));
  if (nonReportArtifactCount > 0) cards.push(makeCard("artifact", `Created ${nonReportArtifactCount} artifact${nonReportArtifactCount === 1 ? "" : "s"}`));
  if (counts.command > 0) cards.push(makeCard("command", `Ran ${counts.command} command${counts.command === 1 ? "" : "s"}`));
  if (counts.review > 0) cards.push(makeCard("review", `Checked ${counts.review} task${counts.review === 1 ? "" : "s"}`));
  return cards.slice(0, 4);
}
const CHAT_HISTORY_KEY = "kendr_chat_history_v1";
const SESSIONS_KEY$1 = "kendr_sessions_v1";
const MAX_STORED_MESSAGES = 200;
const MAX_SESSIONS = 100;
function loadHistory() {
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_KEY);
    if (!raw) return [];
    const msgs = JSON.parse(raw);
    return Array.isArray(msgs) ? msgs.map((m2) => ({ ...m2, ts: new Date(m2.ts) })) : [];
  } catch {
    return [];
  }
}
function saveHistory(messages) {
  try {
    const toSave = messages.filter((m2) => m2.role === "user" || m2.role === "assistant" && ["thinking", "streaming", "awaiting", "done", "error"].includes(String(m2.status || ""))).slice(-MAX_STORED_MESSAGES);
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(toSave));
  } catch (_2) {
  }
}
function loadSessions() {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY$1);
    if (!raw) return [];
    return JSON.parse(raw) || [];
  } catch {
    return [];
  }
}
function saveSessions(sessions) {
  try {
    localStorage.setItem(SESSIONS_KEY$1, JSON.stringify(sessions.slice(-MAX_SESSIONS)));
  } catch {
  }
}
function pruneOldSessions(sessions, retentionDays) {
  if (!retentionDays || retentionDays <= 0) return sessions;
  const cutoff = Date.now() - retentionDays * 24 * 60 * 60 * 1e3;
  return sessions.filter((s) => new Date(s.updatedAt || s.createdAt).getTime() >= cutoff);
}
function makeSessionTitle(messages) {
  const first = messages.find((m2) => m2.role === "user");
  return String(first?.content || "").slice(0, 60) || "New conversation";
}
function formatRelTime(dateStr) {
  const d = new Date(dateStr);
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 6e4) return "just now";
  if (diff < 36e5) return `${Math.floor(diff / 6e4)}m ago`;
  if (diff < 864e5) return `${Math.floor(diff / 36e5)}h ago`;
  return d.toLocaleDateString(void 0, { month: "short", day: "numeric" });
}
function logTimestampMs(value = "") {
  const raw = String(value || "").trim();
  if (!raw) return Number.NaN;
  const direct = Date.parse(raw);
  if (Number.isFinite(direct)) return direct;
  const normalized = raw.replace(" ", "T").replace(",", ".");
  const parsed = Date.parse(normalized);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}
function providerDisplayLabel(provider = "") {
  const normalized = String(provider || "").trim().toLowerCase();
  if (!normalized) return "Model";
  if (normalized === "ollama") return "Local";
  if (normalized === "xai") return "xAI";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}
function hasNativeWebSearchCapability(provider = "", model = "", capabilities = null) {
  if (capabilities && Object.prototype.hasOwnProperty.call(capabilities, "native_web_search")) {
    return !!capabilities.native_web_search;
  }
  const normalizedProvider = String(provider || "").trim().toLowerCase();
  if (normalizedProvider !== "openai") return false;
  const name = String(model || "").trim().toLowerCase();
  if (!name || name.includes("gpt-4.1-nano")) return false;
  if (name.includes("deep-research")) return true;
  return ["gpt-5", "gpt-4o", "gpt-4.1", "o3", "o4-"].some((needle) => name.includes(needle));
}
function synthesizeDeepResearchOption(rawValue, modelInventory) {
  const resolved = resolveSelectedModel(rawValue);
  if (!resolved.provider || !resolved.model) return null;
  const capabilities = {
    native_web_search: hasNativeWebSearchCapability(resolved.provider, resolved.model)
  };
  return {
    value: `${resolved.provider}/${resolved.model}`,
    provider: resolved.provider,
    model: resolved.model,
    label: resolved.label,
    shortLabel: `${providerDisplayLabel(resolved.provider)} · ${resolved.model}`,
    isLocal: resolved.isLocal,
    ready: true,
    contextWindow: resolveContextWindow(rawValue, modelInventory),
    capabilities,
    note: ""
  };
}
function buildDeepResearchModelOptions(modelInventory, inheritedModel = "") {
  const providers = Array.isArray(modelInventory?.providers) ? modelInventory.providers : [];
  const options = [];
  const seen2 = /* @__PURE__ */ new Set();
  for (const providerEntry of providers) {
    const provider = String(providerEntry?.provider || "").trim().toLowerCase();
    if (!provider) continue;
    const ready = provider === "ollama" ? !!providerEntry?.ready : providerEntry?.ready !== false;
    const details = Array.isArray(providerEntry?.selectable_model_details) && providerEntry.selectable_model_details.length ? providerEntry.selectable_model_details : String(providerEntry?.model || "").trim() ? [{
      name: String(providerEntry.model).trim(),
      context_window: Number(providerEntry?.context_window || 0),
      capabilities: providerEntry?.model_capabilities || {}
    }] : [];
    for (const detail of details) {
      const model = String(detail?.name || "").trim();
      if (!model) continue;
      const value = `${provider}/${model}`;
      if (seen2.has(value)) continue;
      seen2.add(value);
      const detailCapabilities = detail?.capabilities && typeof detail.capabilities === "object" ? detail.capabilities : {};
      options.push({
        value,
        provider,
        model,
        label: `${providerDisplayLabel(provider)} · ${model}`,
        shortLabel: `${providerDisplayLabel(provider)} · ${model}`,
        isLocal: provider === "ollama",
        ready,
        contextWindow: Number(detail?.context_window || providerEntry?.context_window || 0),
        capabilities: {
          ...detailCapabilities,
          native_web_search: hasNativeWebSearchCapability(provider, model, detailCapabilities)
        },
        note: String(providerEntry?.note || "").trim()
      });
    }
  }
  const inheritedOption = synthesizeDeepResearchOption(inheritedModel, modelInventory);
  if (inheritedOption && !seen2.has(inheritedOption.value)) options.unshift(inheritedOption);
  return options;
}
function deepResearchModelDisabledReason(option, webSearchEnabled) {
  if (!option) return "Choose a model.";
  if (!option.ready) {
    if (option.provider === "ollama") return "Local model runtime is not ready.";
    return option.note || `${providerDisplayLabel(option.provider)} is not configured.`;
  }
  const modelName = String(option.model || "").trim().toLowerCase();
  if (modelName.includes("image-")) return "Image-only models are not supported for report writing.";
  if (Number(option.contextWindow || 0) > 0 && Number(option.contextWindow || 0) < 32e3) {
    return "Context window is too small for long-form deep research.";
  }
  return "";
}
function scoreDeepResearchOption(option, { webSearchEnabled = true, preferredValue = "" } = {}) {
  if (!option) return Number.NEGATIVE_INFINITY;
  let score = 0;
  const capabilities = option.capabilities && typeof option.capabilities === "object" ? option.capabilities : {};
  const contextWindow = Number(option.contextWindow || 0);
  if (option.value === preferredValue) score += 1e3;
  if (!webSearchEnabled && option.isLocal) score += 240;
  if (webSearchEnabled && hasNativeWebSearchCapability(option.provider, option.model, capabilities)) score += 220;
  else if (webSearchEnabled && capabilities.tool_calling) score += 90;
  if (capabilities.reasoning) score += 140;
  if (capabilities.structured_output) score += 80;
  if (capabilities.tool_calling) score += 70;
  if (!option.isLocal) score += 20;
  const name = String(option.model || "").trim().toLowerCase();
  if (name.includes("gpt-5")) score += 160;
  else if (name.includes("o3")) score += 145;
  else if (name.includes("gpt-4.1")) score += 135;
  else if (name.includes("gpt-4o")) score += 125;
  else if (name.includes("claude")) score += 110;
  else if (name.includes("gemini")) score += 100;
  else if (name.includes("grok")) score += 95;
  else if (name.includes("llama") || name.includes("qwen") || name.includes("mistral")) score += 80;
  if (contextWindow >= 2e5) score += 55;
  else if (contextWindow >= 128e3) score += 35;
  else if (contextWindow >= 64e3) score += 15;
  else if (contextWindow > 0 && contextWindow < 32e3) score -= 180;
  score += Math.min(contextWindow, 2e6) / 24e3;
  return score;
}
function resolveDeepResearchModelSelection({ requestedValue = "", inheritedValue = "", modelInventory = null, webSearchEnabled = true }) {
  const options = buildDeepResearchModelOptions(modelInventory, inheritedValue);
  const optionByValue = new Map(options.map((option) => [option.value, option]));
  const requestedOption = requestedValue ? optionByValue.get(requestedValue) || synthesizeDeepResearchOption(requestedValue, modelInventory) : null;
  const inheritedOption = inheritedValue ? optionByValue.get(inheritedValue) || synthesizeDeepResearchOption(inheritedValue, modelInventory) : null;
  const optionsWithState = options.map((option) => ({
    ...option,
    disabledReason: deepResearchModelDisabledReason(option)
  }));
  const enabledOptions = optionsWithState.filter((option) => !option.disabledReason);
  const requestedReason = deepResearchModelDisabledReason(requestedOption);
  const inheritedReason = deepResearchModelDisabledReason(inheritedOption);
  const recommendedOption = enabledOptions.length ? [...enabledOptions].sort((left, right) => scoreDeepResearchOption(right, { webSearchEnabled, preferredValue: inheritedValue }) - scoreDeepResearchOption(left, { webSearchEnabled, preferredValue: inheritedValue }))[0] : null;
  const effectiveOption = requestedOption && !requestedReason ? requestedOption : inheritedOption && !inheritedReason ? inheritedOption : recommendedOption;
  const effectiveSource = requestedOption && !requestedReason ? "explicit" : inheritedOption && !inheritedReason ? "header" : recommendedOption ? "recommended" : "none";
  return {
    options: optionsWithState,
    requestedOption,
    requestedReason,
    inheritedOption,
    inheritedReason,
    recommendedOption,
    effectiveOption,
    effectiveSource
  };
}
const DEFAULT_SEARCH_PROVIDER_OPTIONS = [
  {
    id: "auto",
    label: "Auto",
    enabled: true,
    authenticated: false,
    rate_limited: false,
    note: "Prefer the strongest configured backend, then fall back automatically.",
    warning: ""
  },
  {
    id: "duckduckgo",
    label: "DuckDuckGo (DDGS)",
    enabled: false,
    authenticated: false,
    rate_limited: true,
    note: "No API key required.",
    warning: "Unauthenticated DDGS search can hit rate limits on heavier runs."
  },
  {
    id: "serpapi",
    label: "SerpAPI",
    enabled: false,
    authenticated: true,
    rate_limited: false,
    note: "Requires SERP_API_KEY.",
    warning: ""
  },
  {
    id: "browser_use_mcp",
    label: "Browser-Use MCP",
    enabled: false,
    authenticated: false,
    rate_limited: false,
    note: "Requires a running browser-use MCP server.",
    warning: ""
  },
  {
    id: "playwright_browser",
    label: "Playwright Browser",
    enabled: false,
    authenticated: false,
    rate_limited: false,
    note: "Requires Playwright plus an installed browser runtime.",
    warning: ""
  }
];
function buildDeepResearchSearchProviders(modelInventory) {
  const rows = Array.isArray(modelInventory?.search_providers) && modelInventory.search_providers.length ? modelInventory.search_providers : DEFAULT_SEARCH_PROVIDER_OPTIONS;
  const seen2 = /* @__PURE__ */ new Set();
  const options = [];
  for (const row of rows) {
    const id2 = String(row?.id || "").trim().toLowerCase();
    if (!id2 || seen2.has(id2)) continue;
    seen2.add(id2);
    options.push({
      id: id2,
      label: String(row?.label || id2).trim() || id2,
      enabled: row?.enabled !== false || id2 === "auto",
      authenticated: !!row?.authenticated,
      rateLimited: !!row?.rate_limited,
      note: String(row?.note || row?.description || "").trim(),
      warning: String(row?.warning || "").trim()
    });
  }
  if (!seen2.has("auto")) options.unshift({ ...DEFAULT_SEARCH_PROVIDER_OPTIONS[0] });
  return options;
}
function resolveDeepResearchSearchProviderSelection(searchProviders, requestedId = "") {
  const options = Array.isArray(searchProviders) ? searchProviders : DEFAULT_SEARCH_PROVIDER_OPTIONS;
  const normalized = String(requestedId || "auto").trim().toLowerCase() || "auto";
  const optionById = new Map(options.map((option) => [option.id, option]));
  const requested = optionById.get(normalized) || optionById.get("auto") || options[0] || null;
  const effective = requested && requested.enabled ? requested : options.find((option) => option.id === "auto") || options.find((option) => option.enabled) || requested;
  return { options, requested, effective };
}
const initChat = {
  messages: [],
  // [{id,role,content,steps,status,runId,artifacts,progress,ts}]
  streaming: false,
  activeRunId: null,
  mode: "chat",
  // chat | plan | agent | research | security
  awaitingContext: null
  // {runId,workflowId,prompt,kind}
};
function chatReducer(s, a) {
  switch (a.type) {
    case "ADD_MSG":
      return { ...s, messages: [...s.messages, a.msg] };
    case "UPD_MSG":
      return { ...s, messages: s.messages.map((m2) => m2.id === a.id ? { ...m2, ...a.patch } : m2) };
    case "APPEND_MSG_CONTENT":
      return {
        ...s,
        messages: s.messages.map((m2) => m2.id === a.id ? { ...m2, content: `${m2.content || ""}${a.delta || ""}` } : m2)
      };
    case "ADD_STEP": {
      const msgs = s.messages.map((m2) => {
        if (m2.id !== a.msgId) return m2;
        const steps = [...m2.steps || []];
        const idx = steps.findIndex((st) => st.stepId === a.step.stepId);
        if (idx >= 0) {
          steps[idx] = { ...steps[idx], ...a.step };
        } else steps.push(a.step);
        return { ...m2, steps };
      });
      return { ...s, messages: msgs };
    }
    case "ADD_PROGRESS": {
      const msgs = s.messages.map((m2) => {
        if (m2.id !== a.msgId) return m2;
        const item = {
          id: String(a.item?.id || `p-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
          slot: String(a.item?.slot || "").trim(),
          ts: a.item?.ts || (/* @__PURE__ */ new Date()).toISOString(),
          title: String(a.item?.title || "").trim(),
          detail: String(a.item?.detail || "").trim(),
          kind: String(a.item?.kind || "").trim(),
          status: String(a.item?.status || "").trim(),
          command: String(a.item?.command || "").trim(),
          cwd: String(a.item?.cwd || "").trim(),
          actor: String(a.item?.actor || "").trim(),
          durationLabel: String(a.item?.durationLabel || "").trim(),
          exitCode: a.item?.exitCode
        };
        if (!item.title && !item.detail) return m2;
        const prev = Array.isArray(m2.progress) ? m2.progress : [];
        const existingIndex = prev.findIndex((entry) => String(entry?.id || "").trim() === item.id || item.slot && String(entry?.slot || "").trim() === item.slot);
        if (existingIndex >= 0) {
          const existing = prev[existingIndex] || {};
          const nextItem = { ...existing, ...item, id: existing.id || item.id };
          if (String(existing.title || "") === nextItem.title && String(existing.detail || "") === nextItem.detail && String(existing.status || "") === nextItem.status) return m2;
          const rest = prev.filter((_2, idx) => idx !== existingIndex);
          return { ...m2, progress: [nextItem, ...rest].slice(0, 14) };
        }
        const last = prev[0];
        if (last && last.title === item.title && last.detail === item.detail) return m2;
        const next = [item, ...prev].slice(0, 14);
        return { ...m2, progress: next };
      });
      return { ...s, messages: msgs };
    }
    case "ADD_LOG_ENTRY": {
      const msgs = s.messages.map((m2) => {
        if (m2.id !== a.msgId) return m2;
        const item = {
          id: String(a.item?.id || `l-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
          ts: String(a.item?.ts || a.item?.timestamp || (/* @__PURE__ */ new Date()).toISOString()).trim(),
          clock: String(a.item?.clock || "").trim(),
          text: String(a.item?.text || "").trim(),
          category: String(a.item?.category || "info").trim()
        };
        if (!item.text) return m2;
        const prev = Array.isArray(m2.logs) ? m2.logs : [];
        if (prev.some((entry) => entry && entry.text === item.text && entry.ts === item.ts)) return m2;
        const next = [...prev, item].sort((left, right) => {
          const leftMs = logTimestampMs(left?.ts || left?.timestamp || "");
          const rightMs = logTimestampMs(right?.ts || right?.timestamp || "");
          if (Number.isFinite(leftMs) && Number.isFinite(rightMs) && leftMs !== rightMs) return leftMs - rightMs;
          if (Number.isFinite(leftMs) !== Number.isFinite(rightMs)) return Number.isFinite(leftMs) ? -1 : 1;
          return String(left?.ts || left?.timestamp || "").localeCompare(String(right?.ts || right?.timestamp || ""));
        }).slice(-1e3);
        return { ...m2, logs: next };
      });
      return { ...s, messages: msgs };
    }
    case "SET_STREAMING":
      return { ...s, streaming: a.val };
    case "SET_RUN":
      return { ...s, activeRunId: a.id };
    case "SET_MODE":
      return { ...s, mode: a.mode };
    case "SET_AWAITING":
      return { ...s, awaitingContext: a.ctx };
    case "CLEAR_AWAITING":
      return { ...s, awaitingContext: null };
    case "CLEAR":
      return { ...initChat, mode: s.mode };
    case "LOAD_MSGS":
      return { ...initChat, mode: s.mode, messages: a.messages };
    default:
      return s;
  }
}
function buildPayload(text, chatId, runId, projectRoot, mode, dr, attachments = [], studioMode = false, useMcp = false) {
  const localPaths = Array.isArray(attachments) ? attachments.map((item) => item.path).filter(Boolean) : [];
  const normalizedText = mode === "agent" ? `Handle this in agent mode. Do the detailed work, think step by step, use attached local files/folders if relevant, and return a concise final answer.

User request: ${text}` : mode === "plan" ? `Use planning mode. Create a concrete execution plan first, keep it concise, ask for approval before implementation, and wait for the user before making changes.

User request: ${text}` : text;
  const base = {
    text: normalizedText,
    channel: "webchat",
    sender_id: "desktop_user",
    chat_id: chatId,
    run_id: runId,
    working_directory: studioMode ? void 0 : projectRoot || void 0,
    use_mcp: useMcp
  };
  if (mode === "agent" || mode === "plan") {
    return {
      ...base,
      local_drive_paths: localPaths.length ? localPaths : void 0,
      local_drive_recursive: localPaths.length ? true : void 0,
      execution_mode: mode === "plan" ? "plan" : void 0,
      planner_mode: mode === "plan" ? "always" : void 0,
      auto_approve_plan: mode === "plan" ? false : void 0
    };
  }
  if (mode !== "research") {
    return {
      ...base,
      local_drive_paths: localPaths.length ? localPaths : void 0,
      local_drive_recursive: localPaths.length ? true : void 0
    };
  }
  const links = (dr.links || "").split(/[\n,\s]+/).map((s) => s.trim()).filter((s) => /^https?:\/\//i.test(s));
  const webLinks = links;
  const remoteSources = dr.webSearchEnabled ? dr.sources : [];
  const mergedLocalPaths = Array.from(/* @__PURE__ */ new Set([...dr.localPaths || [], ...localPaths]));
  const allSources = mergedLocalPaths.length ? Array.from(/* @__PURE__ */ new Set([...remoteSources, "local"])) : remoteSources;
  const depthPreset = resolveDeepResearchDepthPreset(dr.depthMode, dr.pages);
  const payload = {
    ...base,
    deep_research_mode: true,
    long_document_mode: true,
    workflow_type: "deep_research",
    long_document_pages: depthPreset.pages,
    research_depth_mode: depthPreset.id,
    research_output_formats: dr.outputFormats,
    research_citation_style: dr.citationStyle,
    research_enable_plagiarism_check: dr.plagiarismCheck,
    research_web_search_enabled: dr.webSearchEnabled,
    research_search_backend: dr.searchBackend || "auto",
    research_date_range: dr.dateRange,
    research_sources: allSources,
    research_max_sources: dr.maxSources || 0,
    research_checkpoint_enabled: dr.checkpointing,
    research_kb_enabled: !!dr.kbEnabled,
    research_kb_id: dr.kbEnabled ? dr.kbId || "" : "",
    research_kb_top_k: dr.kbTopK || 8,
    deep_research_source_urls: webLinks
  };
  if (dr.multiModelEnabled) {
    payload.multi_model_enabled = true;
    payload.multi_model_strategy = dr.multiModelStrategy === "cheapest" ? "cheapest" : "best";
    const stageOverrides = Object.fromEntries(
      Object.entries(dr.multiModelStageOverrides && typeof dr.multiModelStageOverrides === "object" ? dr.multiModelStageOverrides : {}).map(([stageName, value]) => {
        const resolved = resolveSelectedModel(value);
        if (!resolved.provider || !resolved.model) return null;
        return [
          String(stageName || "").trim(),
          {
            provider: resolved.provider,
            model: resolved.model
          }
        ];
      }).filter(Boolean)
    );
    if (Object.keys(stageOverrides).length) payload.multi_model_stage_overrides = stageOverrides;
  }
  if (mergedLocalPaths.length) {
    payload.local_drive_paths = mergedLocalPaths;
    payload.local_drive_recursive = true;
    payload.local_drive_force_long_document = true;
  }
  return payload;
}
function modeLabel(mode) {
  if (mode === "plan") return "Plan";
  if (mode === "agent") return "Agent";
  if (mode === "research") return "Deep Research";
  return "Chat";
}
function normalizeChecklistStatus(value) {
  const status = String(value || "").trim().toLowerCase();
  if (["completed", "done", "success", "ok"].includes(status)) return "completed";
  if (["running", "in_progress", "started", "active"].includes(status)) return "running";
  if (["awaiting_approval", "awaiting_input", "awaiting"].includes(status)) return "awaiting";
  if (["failed", "error"].includes(status)) return "failed";
  if (["blocked"].includes(status)) return "blocked";
  if (["skipped"].includes(status)) return "skipped";
  return status || "pending";
}
function sanitizeStatusMessage(message) {
  const raw = String(message || "").trim();
  const normalized = raw.toLowerCase();
  if (!raw) return "";
  if (normalized === "resuming run...") return "Continuing approved plan...";
  if (normalized === "restoring context from the paused run...") return "Loading paused checklist...";
  if (normalized === "executing queued tasks...") return "Running remaining checklist steps...";
  if (normalized === "collecting outputs and preparing the final response...") return "Wrapping up final answer...";
  return raw;
}
function extractChecklist(result) {
  if (!result || typeof result !== "object") return [];
  const shellSteps = Array.isArray(result.shell_plan_steps) ? result.shell_plan_steps : [];
  if (shellSteps.length) {
    return shellSteps.map((step, index2) => ({
      step: Number(step.step || index2 + 1),
      title: String(step.title || step.description || `Step ${index2 + 1}`).trim() || `Step ${index2 + 1}`,
      status: normalizeChecklistStatus(step.status || (step.done ? "completed" : "pending")),
      detail: String(step.detail || step.reason || "").trim(),
      command: String(step.command || "").trim(),
      stdout: String(step.stdout || "").trim(),
      stderr: String(step.stderr || "").trim(),
      reason: String(step.reason || "").trim(),
      optional: !!step.optional,
      done: !!step.done || ["completed", "skipped"].includes(normalizeChecklistStatus(step.status)),
      returnCode: step.return_code
    }));
  }
  const planSteps = Array.isArray(result.plan_steps) ? result.plan_steps : [];
  if (planSteps.length) {
    const activeIndex = Math.max(0, Number(result.plan_step_index || 0));
    return planSteps.map((step, index2) => {
      const rawStatus = normalizeChecklistStatus(step.status || "");
      const status = rawStatus || (index2 < activeIndex ? "completed" : index2 === activeIndex ? "running" : "pending");
      return {
        step: index2 + 1,
        title: String(step.title || step.name || step.description || `Step ${index2 + 1}`).trim() || `Step ${index2 + 1}`,
        status,
        detail: String(step.success_criteria || step.description || "").trim(),
        command: "",
        stdout: "",
        stderr: "",
        reason: String(step.reason || "").trim(),
        optional: false,
        done: ["completed", "skipped"].includes(status),
        returnCode: null
      };
    });
  }
  return [];
}
function latestChecklistMessage(messages) {
  const safe = Array.isArray(messages) ? messages : [];
  for (let i = safe.length - 1; i >= 0; i -= 1) {
    const msg = safe[i];
    if (msg?.role === "assistant" && Array.isArray(msg?.checklist) && msg.checklist.length) return msg;
  }
  return null;
}
function shouldInlineAwaitingContext(ctx) {
  if (!ctx || typeof ctx !== "object") return false;
  return hasConcreteAwaitingContext(ctx) && !isSkillApproval(ctx.kind, ctx.approvalRequest);
}
function buildSimpleHistory(messages, maxTurns = 12) {
  const safe = Array.isArray(messages) ? messages : [];
  return safe.filter((m2) => (m2?.role === "user" || m2?.role === "assistant") && String(m2?.content || "").trim() && !["thinking", "streaming"].includes(String(m2?.status || ""))).slice(-maxTurns).map((m2) => ({
    role: m2.role,
    content: String(m2.content || "").trim()
  }));
}
function estimateObjectTokens(value) {
  try {
    const raw = JSON.stringify(value);
    return Math.max(0, Math.round(String(raw || "").length / 4));
  } catch {
    return 0;
  }
}
function formatDuration$2(totalSeconds) {
  const s = Math.max(0, Number(totalSeconds) || 0);
  const h2 = Math.floor(s / 3600);
  const m2 = Math.floor(s % 3600 / 60);
  const sec = s % 60;
  if (h2 > 0) return `${h2}h ${m2}m ${sec}s`;
  if (m2 > 0) return `${m2}m ${sec}s`;
  return `${sec}s`;
}
function summarizeLogFeed(logs = []) {
  const items = Array.isArray(logs) ? logs : [];
  if (!items.length) return "Waiting for execution log output...";
  const latest = String(items[items.length - 1]?.text || "").trim();
  if (!latest) return `${items.length} log update${items.length === 1 ? "" : "s"} captured`;
  const clipped = latest.length > 120 ? `${latest.slice(0, 117)}...` : latest;
  return `${items.length} log update${items.length === 1 ? "" : "s"} captured. Latest: ${clipped}`;
}
const GENERIC_PROGRESS_TITLES = /* @__PURE__ */ new Set(["runtime update", "activity"]);
function normalizeLiveProgressItem(item = null) {
  const safe = item && typeof item === "object" ? item : {};
  const rawTitle = String(safe.title || "").trim();
  const rawDetail = String(safe.detail || "").trim();
  const genericTitle = GENERIC_PROGRESS_TITLES.has(rawTitle.toLowerCase());
  const title = genericTitle && rawDetail ? rawDetail : rawTitle || rawDetail;
  const detail = genericTitle && rawDetail ? "" : rawDetail && rawDetail !== title ? rawDetail : "";
  return {
    ...safe,
    title,
    detail,
    kind: String(safe.kind || "activity").trim().toLowerCase(),
    status: String(safe.status || "running").trim().toLowerCase(),
    actor: String(safe.actor || "").trim(),
    durationLabel: String(safe.durationLabel || "").trim(),
    cwd: String(safe.cwd || "").trim(),
    command: String(safe.command || "").trim()
  };
}
function buildLiveProgressItem(progress = [], statusText = "", fallbackStatus = "") {
  const items = Array.isArray(progress) ? progress : [];
  for (const item of items) {
    const normalized = normalizeLiveProgressItem(item);
    if (normalized.title) return normalized;
  }
  const detail = sanitizeStatusMessage(statusText);
  if (!detail) return null;
  return {
    id: "runtime-status-fallback",
    slot: "runtime-status",
    title: detail,
    detail: "",
    kind: "status",
    status: String(fallbackStatus || "running").trim().toLowerCase(),
    actor: "",
    durationLabel: "",
    cwd: "",
    command: ""
  };
}
function liveProgressLabel(item = null) {
  const kind = String(item?.kind || "").trim().toLowerCase();
  if (kind === "status") return "Runtime";
  if (kind === "step") return "Current Step";
  if (kind === "intent") return "Research Intent";
  if (kind === "source_strategy") return "Source Strategy";
  if (kind === "coverage") return "Coverage";
  if (kind === "artifact_created") return "Artifacts";
  if (kind === "quality_gate") return "Quality Check";
  if (kind === "gap_detected") return "Gap Review";
  return "Current Step";
}
function isPendingRunStatus(status) {
  return ["thinking", "streaming", "awaiting"].includes(String(status || "").trim().toLowerCase());
}
function isStreamingRunStatus(status) {
  return ["thinking", "streaming"].includes(String(status || "").trim().toLowerCase());
}
function failureMessageForRecoveredRun(runId, status = "") {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "failed") return `Run ${runId} failed while the app was offline.`;
  if (normalized === "cancelled") return `Run ${runId} was cancelled while the app was offline.`;
  return `Run ${runId} could not be recovered after the app restarted.`;
}
const EXECUTION_LOG_LINE_RE = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - ([A-Z]+) - (.*)$/;
function executionLogClockLabel(value = "") {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const match = raw.match(/\b(\d{2}:\d{2}:\d{2})\b/);
  return match ? match[1] : raw;
}
function compactExecutionLogText(value, limit = 220) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, limit - 3).trimEnd()}...` : text;
}
function executionLogDisplayName(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.replace(/_agent$/i, "").replace(/_/g, " ").trim();
}
function executionLogBasename(value) {
  const text = String(value || "").trim().replace(/^["']|["']$/g, "");
  if (!text) return "";
  const normalized = text.replace(/\\/g, "/").replace(/\/+$/, "");
  const idx = normalized.lastIndexOf("/");
  return idx >= 0 ? normalized.slice(idx + 1) : normalized;
}
function summarizeExecutionLogMessage(message) {
  const raw = String(message || "").trim();
  if (!raw || raw === "[LLM Prompt]") return null;
  if (raw.startsWith("[LLM Call]")) {
    const agent = raw.match(/agent=([^|]+)/i)?.[1]?.trim();
    const model = raw.match(/model=([^|]+)/i)?.[1]?.trim();
    const promptChars = raw.match(/prompt_chars=(\d+)/i)?.[1]?.trim();
    const parts = ["LLM call"];
    if (agent) parts.push(executionLogDisplayName(agent));
    if (model) parts.push(model);
    if (promptChars) parts.push(`${Number(promptChars).toLocaleString()} prompt chars`);
    return { text: parts.filter(Boolean).join(" · "), category: "llm_call" };
  }
  if (raw.startsWith("[LLM OK]")) {
    const agent = raw.match(/agent=([^|]+)/i)?.[1]?.trim();
    const model = raw.match(/model=([^|]+)/i)?.[1]?.trim();
    const elapsed = raw.match(/elapsed_ms=(\d+)/i)?.[1]?.trim();
    const parts = ["LLM response"];
    if (agent) parts.push(executionLogDisplayName(agent));
    if (model) parts.push(model);
    if (elapsed) parts.push(`${Math.round(Number(elapsed))} ms`);
    return { text: parts.filter(Boolean).join(" · "), category: "llm_ok" };
  }
  if (raw.startsWith("[files] wrote:")) {
    const path = raw.split(":").slice(1).join(":").trim();
    return {
      text: `Wrote artifact · ${executionLogBasename(path) || compactExecutionLogText(path)}`,
      category: "artifact"
    };
  }
  return {
    text: compactExecutionLogText(raw.replace(/^\[([^\]]+)\]\s*/, "$1 · ")),
    category: "info"
  };
}
function summarizeExecutionLogContinuation(line) {
  const raw = String(line || "").trim();
  if (!raw) return null;
  if (/^[A-Za-z]:[\\/]/.test(raw) || raw.startsWith("/")) {
    const name = executionLogBasename(raw);
    return name ? { text: `File · ${name}`, category: "file" } : null;
  }
  if (/^characters:/i.test(raw)) {
    return { text: compactExecutionLogText(raw, 120), category: "meta" };
  }
  if (/^reason:/i.test(raw)) {
    return { text: `Reason · ${compactExecutionLogText(raw.replace(/^reason:/i, ""), 160)}`, category: "meta" };
  }
  return null;
}
function parseExecutionLogLine(line, state = {}) {
  const raw = String(line || "").replace(/\r?\n$/, "");
  if (!raw.trim()) return null;
  const match = raw.match(EXECUTION_LOG_LINE_RE);
  if (match) {
    state.skipMultiline = false;
    state.lastTimestamp = match[1];
    const message = String(match[3] || "").trim();
    if (message === "[LLM Prompt]") {
      state.skipMultiline = true;
      return null;
    }
    const summary2 = summarizeExecutionLogMessage(message);
    if (!summary2?.text) return null;
    return {
      ts: state.lastTimestamp || "",
      clock: executionLogClockLabel(state.lastTimestamp || ""),
      text: summary2.text,
      category: summary2.category || "info"
    };
  }
  if (state.skipMultiline) return null;
  const summary = summarizeExecutionLogContinuation(raw);
  if (!summary?.text) return null;
  return {
    ts: String(state.lastTimestamp || "").trim(),
    clock: executionLogClockLabel(state.lastTimestamp || ""),
    text: summary.text,
    category: summary.category || "info"
  };
}
function buildExecutionLogSignature(item = {}) {
  return `${String(item.ts || item.timestamp || "").trim()}|${String(item.text || "").trim()}`;
}
const GENERIC_AWAITING_TEXTS = /* @__PURE__ */ new Set([
  "waiting for your input",
  "waiting for your input.",
  "need clarification",
  "need confirmation",
  "approval required",
  "permission required",
  "plan approval needed",
  "run paused for your input. reply here to continue the same workflow.",
  "kendr paused this run, but the backend did not provide the exact question. review the latest execution log and reply with what should happen next.",
  "waiting for your reply above...",
  "waiting for execution log output..."
]);
function normalizeAwaitingText(value = "") {
  return String(value || "").replace(/\u2026/g, "...").replace(/\s+/g, " ").trim().toLowerCase();
}
function isMeaningfulAwaitingText(value = "") {
  const normalized = normalizeAwaitingText(value);
  return !!normalized && !GENERIC_AWAITING_TEXTS.has(normalized);
}
function sectionHasMeaningfulAwaitingText(section = {}) {
  if (!section || typeof section !== "object") return false;
  if (isMeaningfulAwaitingText(section.title)) return true;
  const items = Array.isArray(section.items) ? section.items : [];
  return items.some((item) => {
    if (typeof item === "string") return isMeaningfulAwaitingText(item);
    if (!item || typeof item !== "object") return false;
    return isMeaningfulAwaitingText(item.title) || isMeaningfulAwaitingText(item.text) || isMeaningfulAwaitingText(item.label) || isMeaningfulAwaitingText(item.value);
  });
}
function hasConcreteAwaitingRequest(request = null) {
  const safe = request && typeof request === "object" ? request : {};
  const sections = Array.isArray(safe.sections) ? safe.sections : [];
  return !!(isMeaningfulAwaitingText(safe.summary) || isMeaningfulAwaitingText(safe.title) || isMeaningfulAwaitingText(safe.help_text) || sections.some(sectionHasMeaningfulAwaitingText));
}
const ACTIVE_RUN_STATUSES = /* @__PURE__ */ new Set(["running", "started", "cancelling"]);
const TERMINAL_RUN_STATUSES = /* @__PURE__ */ new Set(["completed", "failed", "cancelled"]);
function runSnapshotResult(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  return data.result && typeof data.result === "object" ? data.result : {};
}
function runSnapshotStatus(snapshot, fallbackStatus = "") {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = runSnapshotResult(data);
  return String(data.status || result.status || fallbackStatus || "").trim().toLowerCase();
}
function runSnapshotApprovalRequest(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = runSnapshotResult(data);
  return result.approval_request && typeof result.approval_request === "object" ? result.approval_request : data.approval_request && typeof data.approval_request === "object" ? data.approval_request : {};
}
function runSnapshotSignalsAwaiting(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = runSnapshotResult(data);
  const status = runSnapshotStatus(data);
  if (ACTIVE_RUN_STATUSES.has(status) || TERMINAL_RUN_STATUSES.has(status)) return false;
  return !!(status === "awaiting_user_input" || result.awaiting_user_input || data.awaiting_user_input || result.plan_waiting_for_approval || result.plan_needs_clarification || result.pending_user_input_kind || data.pending_user_input_kind || result.approval_pending_scope || data.approval_pending_scope || result.pending_user_question || data.pending_user_question || Object.keys(runSnapshotApprovalRequest(data)).length > 0);
}
function runSnapshotAwaitingPrompt(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = runSnapshotResult(data);
  return String(result.pending_user_question || data.pending_user_question || "").trim();
}
function runSnapshotAwaitingScope(snapshot, fallbackScope = "") {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = runSnapshotResult(data);
  return String(result.approval_pending_scope || data.approval_pending_scope || fallbackScope || "").trim();
}
function runSnapshotAwaitingKind(snapshot, fallbackKind = "") {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = runSnapshotResult(data);
  return String(result.pending_user_input_kind || data.pending_user_input_kind || fallbackKind || "").trim();
}
function normalizeAwaitingRequest(request = null, prompt2 = "", scope = "", kind = "") {
  const safe = request && typeof request === "object" ? request : {};
  const sections = Array.isArray(safe.sections) ? safe.sections.filter(sectionHasMeaningfulAwaitingText) : [];
  const actions = safe.actions && typeof safe.actions === "object" ? safe.actions : {};
  const summary = String(safe.summary || prompt2 || "").trim();
  const helpText = String(safe.help_text || "").trim();
  const explicitTitle = String(safe.title || "").trim();
  const derivedTitle = explicitTitle || awaitingTitleFromContext(scope, kind, safe);
  const normalized = {
    ...safe,
    actions
  };
  if (summary) normalized.summary = summary;
  else delete normalized.summary;
  if (helpText) normalized.help_text = helpText;
  else delete normalized.help_text;
  if (explicitTitle) normalized.title = explicitTitle;
  else if (isMeaningfulAwaitingText(derivedTitle) && (summary || helpText || sections.length || hasExplicitAwaitingActions(safe))) normalized.title = derivedTitle;
  else delete normalized.title;
  if (sections.length) normalized.sections = sections;
  else delete normalized.sections;
  return normalized;
}
function resolveRunSnapshotLogPath(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const logPaths = data.log_paths && typeof data.log_paths === "object" ? data.log_paths : {};
  const direct = String(logPaths.execution_log || "").trim();
  if (direct) return direct;
  const runDir = String(data.run_output_dir || data.output_dir || data.resume_output_dir || "").trim();
  if (!runDir) return "";
  const normalized = runDir.replace(/[\\/]+$/, "");
  const separator = normalized.includes("\\") ? "\\" : "/";
  return `${normalized}${separator}execution.log`;
}
function runSnapshotOutputText(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = data.result && typeof data.result === "object" ? data.result : {};
  return String(
    result.final_output || result.output || result.draft_response || result.response || data.final_output || data.output || data.response || ""
  ).trim();
}
function runSnapshotErrorText(snapshot, runId, fallbackStatus = "") {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = runSnapshotResult(data);
  const status = runSnapshotStatus(data, fallbackStatus);
  const detail = String(
    data.last_error || result.last_error || data.error || result.error || runSnapshotOutputText(snapshot)
  ).trim();
  if (detail) return detail;
  if (status === "failed" || status === "cancelled") return failureMessageForRecoveredRun(runId, status);
  return "";
}
function runSnapshotArtifacts(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = runSnapshotResult(data);
  const artifacts = [];
  const seen2 = /* @__PURE__ */ new Set();
  const appendArtifact = (artifact) => {
    const normalized = normalizeArtifactItem(artifact);
    if (!normalized) return;
    const key = [
      String(normalized.name || "").trim(),
      String(normalized.path || "").trim(),
      String(normalized.downloadUrl || "").trim(),
      String(normalized.viewUrl || "").trim()
    ].join("::");
    if (seen2.has(key)) return;
    seen2.add(key);
    artifacts.push(normalized);
  };
  const appendArtifactList = (items) => {
    if (!Array.isArray(items)) return;
    for (const item of items) appendArtifact(item);
  };
  const appendCardArtifacts = (card) => {
    const safeCard = card && typeof card === "object" ? card : {};
    appendArtifactList(safeCard.created_artifacts);
    appendArtifactList(safeCard.downloadable_reports);
  };
  appendArtifactList(result.artifact_files);
  appendArtifactList(data.artifact_files);
  appendCardArtifacts(result.deep_research_result_card);
  appendCardArtifacts(data.deep_research_result_card);
  const appendManifestArtifacts = (manifest) => {
    if (!manifest || typeof manifest !== "object") return;
    appendArtifactList(manifest.created_artifacts);
  };
  appendManifestArtifacts(result.deep_research_artifacts_manifest);
  appendManifestArtifacts(data.deep_research_artifacts_manifest);
  const appendExportHints = (items) => {
    if (!Array.isArray(items)) return;
    for (const item of items) {
      const safe = item && typeof item === "object" ? item : {};
      const ext = String(safe.ext || "").trim().toLowerCase();
      const name = String(safe.name || safe.label || (ext ? `report.${ext}` : "")).trim();
      if (!name) continue;
      appendArtifact({
        name,
        label: String(safe.label || name).trim(),
        ext,
        kind: "report",
        download_url: safe.download_url || safe.downloadUrl || "",
        view_url: safe.view_url || safe.viewUrl || ""
      });
    }
  };
  appendExportHints(result.long_document_exports);
  appendExportHints(data.long_document_exports);
  for (const key of [
    "long_document_compiled_path",
    "long_document_compiled_html_path",
    "long_document_compiled_pdf_path",
    "long_document_compiled_docx_path"
  ]) {
    const candidate = String(result[key] || data[key] || "").trim();
    if (!candidate) continue;
    appendArtifact({
      name: basename$1(candidate),
      path: candidate,
      kind: "report"
    });
  }
  return artifacts;
}
const REPORT_ARTIFACT_NAMES = /* @__PURE__ */ new Set([
  "report.md",
  "report.html",
  "report.pdf",
  "report.docx",
  "deep_research_report.md",
  "deep_research_report.html",
  "deep_research_report.pdf",
  "deep_research_report.docx"
]);
function hasReportArtifacts(items) {
  if (!Array.isArray(items) || !items.length) return false;
  return items.some((item) => {
    const safe = item && typeof item === "object" ? item : {};
    const name = String(safe.name || safe.label || safe.path || "").trim().toLowerCase();
    if (!name) return false;
    const base = basename$1(name).toLowerCase();
    if (REPORT_ARTIFACT_NAMES.has(base)) return true;
    const ext = String(safe.ext || "").trim().toLowerCase();
    return !!ext && ["md", "html", "pdf", "docx"].includes(ext) && (base.startsWith("report.") || base.startsWith("deep_research_report."));
  });
}
function runSnapshotChecklist(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = data.result && typeof data.result === "object" ? data.result : {};
  return extractChecklist(Object.keys(result).length ? result : data);
}
function runSnapshotMessageMeta(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const status = runSnapshotStatus(data);
  const logPath = resolveRunSnapshotLogPath(data);
  return {
    runStartedAt: data.started_at || data.created_at || "",
    runOutputDir: String(data.run_output_dir || data.output_dir || data.resume_output_dir || "").trim(),
    executionLogPath: logPath,
    lastKnownRunStatus: status,
    lastError: runSnapshotErrorText(data, String(data.run_id || "").trim(), status)
  };
}
function approvalScopeLabel(scope = "") {
  return String(scope || "").trim().replace(/[_-]+/g, " ");
}
function awaitingTitleFromContext(scope = "", kind = "", request = null) {
  const explicit = String(request?.title || "").trim();
  if (explicit) return explicit;
  const scopeText = String(scope || "").trim().toLowerCase();
  const kindText = String(kind || "").trim().toLowerCase();
  if (kindText.includes("clar") || scopeText.includes("clar")) return "Need clarification";
  if (kindText.includes("confirm") || scopeText.includes("confirm")) return "Need confirmation";
  if (kindText.includes("approval") || scopeText.includes("approval")) return "Approval required";
  if (kindText.includes("permission") || scopeText.includes("permission")) return "Permission required";
  if (scopeText.includes("plan")) return "Plan approval needed";
  return "Waiting for your input";
}
function hasExplicitAwaitingActions(request = null) {
  const actions = request && typeof request === "object" && request.actions && typeof request.actions === "object" ? request.actions : {};
  return !!(String(actions.accept_label || "").trim() || String(actions.reject_label || "").trim() || String(actions.suggest_label || "").trim());
}
function isApprovalLikeAwaiting(scope = "", kind = "", request = null) {
  if (hasExplicitAwaitingActions(request)) return true;
  const scopeText = String(scope || "").trim().toLowerCase();
  const kindText = String(kind || "").trim().toLowerCase();
  return scopeText.includes("approval") || scopeText.includes("permission") || scopeText.includes("plan") || kindText.includes("approval") || kindText.includes("permission") || kindText.includes("confirm");
}
function buildAwaitingState(snapshot, fallback = {}) {
  if (!runSnapshotSignalsAwaiting(snapshot)) return null;
  const prompt2 = runSnapshotAwaitingPrompt(snapshot);
  const scope = runSnapshotAwaitingScope(snapshot, fallback?.approvalScope || "");
  const kind = runSnapshotAwaitingKind(snapshot, fallback?.approvalKind || "");
  const normalizedRequest = normalizeAwaitingRequest(runSnapshotApprovalRequest(snapshot), prompt2, scope, kind);
  const summary = String(normalizedRequest.summary || prompt2 || "").trim();
  const helpText = String(normalizedRequest.help_text || "").trim();
  const title = String(normalizedRequest.title || "").trim();
  if (!isMeaningfulAwaitingText(prompt2) && !hasConcreteAwaitingRequest(normalizedRequest)) return null;
  return {
    content: summary,
    status: "awaiting",
    statusText: summary || helpText || title || "Waiting for your input.",
    approvalScope: scope,
    approvalKind: kind,
    approvalRequest: normalizedRequest,
    approvalState: "pending",
    awaitingDecision: isApprovalLikeAwaiting(scope, kind, normalizedRequest) ? "approval" : "reply"
  };
}
function buildAwaitingContext(snapshot, runId, messageId, awaitingState = null) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : {};
  const result = runSnapshotResult(data);
  const awaiting = awaitingState || buildAwaitingState(data);
  if (!awaiting) return null;
  return {
    runId,
    workflowId: String(data.workflow_id || result.workflow_id || runId),
    messageId,
    prompt: awaiting.content || awaiting.statusText || "",
    kind: awaiting.approvalKind || "",
    scope: awaiting.approvalScope || "",
    approvalRequest: awaiting.approvalRequest || null
  };
}
function invalidAwaitingMessage(snapshot, runId, fallback = {}) {
  const latestLog = String((Array.isArray(fallback?.logs) ? fallback.logs[0]?.text : "") || "").trim();
  const scope = approvalScopeLabel(
    snapshot?.result?.approval_pending_scope || snapshot?.approval_pending_scope || fallback?.approvalScope || ""
  );
  const parts = [`Run ${runId} paused without asking a concrete question.`];
  if (scope) parts.push(`Reported scope: ${scope}.`);
  if (latestLog) parts.push(`Latest log: ${latestLog}`);
  else {
    const detail = runSnapshotErrorText(snapshot, runId, String(snapshot?.status || snapshot?.result?.status || ""));
    if (detail) parts.push(detail);
  }
  return parts.join(" ");
}
function messageHasConcreteAwaitingPrompt(msg) {
  const approvalRequest = msg?.approvalRequest && typeof msg.approvalRequest === "object" ? msg.approvalRequest : {};
  return !!(isMeaningfulAwaitingText(msg?.content || "") || hasConcreteAwaitingRequest(approvalRequest));
}
function hasConcreteAwaitingContext(ctx) {
  if (!ctx || typeof ctx !== "object") return false;
  return isMeaningfulAwaitingText(ctx.prompt) || hasConcreteAwaitingRequest(ctx.approvalRequest);
}
function hasDisplayableAwaitingContext(ctx) {
  if (!ctx || typeof ctx !== "object") return false;
  return isSkillApproval(ctx.kind, ctx.approvalRequest) || hasConcreteAwaitingContext(ctx);
}
function clearAwaitingMessageFields(patch = {}) {
  return {
    ...patch,
    approvalScope: "",
    approvalKind: "",
    approvalRequest: null,
    awaitingDecision: "",
    approvalState: ""
  };
}
function buildRunningMessagePatch(snapshot, fallback = {}) {
  const latestLog = String((Array.isArray(fallback?.logs) ? fallback.logs[0]?.text : "") || "").trim();
  const fallbackWasAwaiting = String(fallback?.status || "").trim().toLowerCase() === "awaiting";
  const fallbackStatusText = !fallbackWasAwaiting && isMeaningfulAwaitingText(fallback?.statusText) ? String(fallback.statusText).trim() : "";
  const fallbackContent = !fallbackWasAwaiting && isMeaningfulAwaitingText(fallback?.content) ? String(fallback.content).trim() : "";
  return clearAwaitingMessageFields({
    ...runSnapshotMessageMeta(snapshot),
    content: fallbackContent,
    status: "streaming",
    statusText: isMeaningfulAwaitingText(latestLog) ? latestLog : fallbackStatusText
  });
}
function buildCompletedMessagePatch(snapshot, fallback = {}) {
  const fallbackWasAwaiting = String(fallback?.status || "").trim().toLowerCase() === "awaiting";
  return clearAwaitingMessageFields({
    ...runSnapshotMessageMeta(snapshot),
    content: runSnapshotOutputText(snapshot) || (fallbackWasAwaiting ? "" : String(fallback?.content || "").trim()),
    status: "done",
    statusText: "",
    artifacts: runSnapshotArtifacts(snapshot),
    checklist: runSnapshotChecklist(snapshot)
  });
}
function buildFailedMessagePatch(snapshot, runId, fallbackStatus = "", fallback = {}) {
  return clearAwaitingMessageFields({
    ...runSnapshotMessageMeta(snapshot),
    content: runSnapshotErrorText(snapshot, runId, fallbackStatus) || invalidAwaitingMessage(snapshot, runId, fallback),
    status: "error",
    statusText: "",
    artifacts: runSnapshotArtifacts(snapshot),
    checklist: runSnapshotChecklist(snapshot)
  });
}
function buildInvalidAwaitingErrorPatch(snapshot, runId, fallback = {}) {
  return clearAwaitingMessageFields({
    ...runSnapshotMessageMeta(snapshot),
    content: invalidAwaitingMessage(snapshot, runId, fallback),
    status: "error",
    statusText: "",
    artifacts: runSnapshotArtifacts(snapshot),
    checklist: runSnapshotChecklist(snapshot)
  });
}
function buildInvalidAwaitingRunningPatch(snapshot, fallback = {}, statusText = "Run sent an invalid pause signal. Rechecking backend status...") {
  return {
    ...buildRunningMessagePatch(snapshot, fallback),
    statusText,
    artifacts: runSnapshotArtifacts(snapshot),
    checklist: runSnapshotChecklist(snapshot)
  };
}
function isShellProgressItem$2(item) {
  if (!item || typeof item !== "object") return false;
  const kind = String(item.kind || "").toLowerCase();
  const title = String(item.title || "").toLowerCase();
  const detail = String(item.detail || "").toLowerCase();
  const command = String(item.command || "").trim();
  if (command) return true;
  if (kind.includes("command") || kind.includes("shell")) return true;
  return /\bshell command\b|\brunning command\b|\bos[_\s-]?agent\b/.test(`${title} ${detail}`);
}
function shellCardFromProgress(progress = []) {
  const items = (Array.isArray(progress) ? progress : []).filter(isShellProgressItem$2);
  if (!items.length) return null;
  const running = items.find((it) => ["running", "started", "in_progress"].includes(String(it.status || "").toLowerCase()));
  const primary = running || items[0];
  if (!primary) return null;
  const primaryStatus = String(primary.status || "").toLowerCase();
  const command = String(primary.command || "").trim();
  let output = "";
  if (["completed", "failed", "error"].includes(primaryStatus)) {
    output = String(primary.detail || "").trim();
  } else if (command) {
    const companion = items.find((it) => it !== primary && String(it.command || "").trim() === command && ["completed", "failed", "error"].includes(String(it.status || "").toLowerCase()) && String(it.detail || "").trim());
    if (companion) output = String(companion.detail || "").trim();
  }
  return {
    title: String(primary.title || "Shell command").trim() || "Shell command",
    command,
    output,
    status: primaryStatus || "running",
    cwd: String(primary.cwd || "").trim(),
    durationLabel: String(primary.durationLabel || "").trim(),
    exitCode: primary.exitCode
  };
}
function inferExecutionBlockers({ msg, shellCard, progress = [], checklist = [] }) {
  const textParts = [];
  const addText = (value) => {
    const raw = String(value || "").trim();
    if (raw) textParts.push(raw);
  };
  addText(msg?.content);
  addText(shellCard?.output);
  for (const item of Array.isArray(progress) ? progress : []) {
    addText(item?.title);
    addText(item?.detail);
  }
  for (const item of Array.isArray(checklist) ? checklist : []) {
    addText(item?.title);
    addText(item?.detail);
    addText(item?.reason);
    addText(item?.stdout);
    addText(item?.stderr);
  }
  const observedMatch = String(msg?.content || "").match(/Observed blockers:\s*([\s\S]*?)(?:\n\s*\n|$)/i);
  if (observedMatch?.[1]) {
    for (const line of observedMatch[1].split("\n")) {
      const cleaned = line.replace(/^\s*-\s*/, "").trim();
      if (cleaned) textParts.push(cleaned);
    }
  }
  const corpus = textParts.join("\n").toLowerCase();
  if (!corpus.trim()) return [];
  const chips = [];
  const pushChip = (key, label, tone = "warn") => {
    if (chips.some((item) => item.key === key)) return;
    chips.push({ key, label, tone });
  };
  if (/dockerdesktoplinuxengine|docker engine\/desktop was not actually running|docker engine not responding|cannot connect to the docker daemon|docker daemon|the system cannot find the file specified.*docker/i.test(corpus)) {
    pushChip("engine-down", "Engine Down", "err");
  }
  if (/wrong shell|not a valid statement separator|\/dev\/null|command -v|planner emitted syntax for the wrong shell|powershell plan uses|is not recognized as the name of a cmdlet|unexpected token '\|\|'/i.test(corpus)) {
    pushChip("wrong-shell", "Wrong Shell", "err");
  }
  if (/required app\/tool was missing|not discoverable from this machine|cannot find the file specified|was not found|could not find|not recognized as the name of a cmdlet|no such file or directory|missing or not discoverable/i.test(corpus)) {
    pushChip("app-missing", "App Missing", "warn");
  }
  if (/outside the allowed execution scope|outside the allowed scope|blocked by execution policy|policy block|approval_required|requires your approval/i.test(corpus)) {
    pushChip("policy-block", "Policy Block", "warn");
  }
  if (/permission denied|access is denied|administrator|elevation required|sudo|operation not permitted/i.test(corpus)) {
    pushChip("permission", "Need Permission", "warn");
  }
  if (/timed out|timeout|could not resolve|temporary failure in name resolution|connection refused|network is unreachable|failed to fetch/i.test(corpus)) {
    pushChip("network", "Network Issue", "warn");
  }
  const blockedSteps = (Array.isArray(checklist) ? checklist : []).filter((item) => {
    const status = normalizeChecklistStatus(item?.status);
    return status === "blocked" || status === "failed";
  }).length;
  if (!chips.length && blockedSteps > 0) {
    pushChip("blocked", blockedSteps > 1 ? "Steps Blocked" : "Step Blocked", "warn");
  }
  return chips.slice(0, 4);
}
function readBlobAsDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("read_failed"));
    reader.readAsDataURL(blob);
  });
}
function detectAttachmentType(filePath, fallback = "file") {
  const raw = String(filePath || "").trim().toLowerCase();
  if (!raw) return fallback;
  if (/\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(raw)) return "image";
  return fallback;
}
function attachmentPreviewSrc(item) {
  if (!item || item.type !== "image") return "";
  const preview = String(item.previewUrl || "").trim();
  if (preview) return preview;
  const rawPath = String(item.path || "").trim();
  if (!rawPath) return "";
  const normalized = rawPath.replace(/\\/g, "/");
  if (/^[a-z]:\//i.test(normalized)) return `file:///${normalized}`;
  if (normalized.startsWith("/")) return `file://${normalized}`;
  return rawPath;
}
const DR_DEFAULTS = {
  depthMode: "standard",
  pages: 25,
  researchModel: "",
  searchBackend: "auto",
  citationStyle: "apa",
  dateRange: "all_time",
  maxSources: 0,
  outputFormats: ["pdf", "docx", "html", "md"],
  webSearchEnabled: true,
  sources: ["web"],
  plagiarismCheck: true,
  checkpointing: false,
  localPaths: [],
  // native FS paths (Electron folder picker)
  links: "",
  // newline-separated URLs
  kbEnabled: false,
  kbId: "",
  kbTopK: 8,
  multiModelEnabled: false,
  multiModelStrategy: "best",
  multiModelStageOverrides: {},
  collapsed: false
};
const DEEP_RESEARCH_DEPTH_PRESETS = [
  {
    id: "brief",
    pages: 10,
    label: "Focused Brief",
    summary: "Focused",
    hint: "Fastest run for a narrower scope and the most important findings."
  },
  {
    id: "standard",
    pages: 25,
    label: "Standard Report",
    summary: "Standard",
    hint: "Balanced depth for most multi-section research tasks."
  },
  {
    id: "comprehensive",
    pages: 50,
    label: "Comprehensive Study",
    summary: "Comprehensive",
    hint: "Broader source sweep and deeper synthesis across sections."
  },
  {
    id: "exhaustive",
    pages: 100,
    label: "Exhaustive Dossier",
    summary: "Exhaustive",
    hint: "Maximum breadth and depth; slower and more resource-intensive."
  }
];
function normalizeDeepResearchDepthMode(value, pages) {
  const normalized = String(value || "").trim().toLowerCase();
  if (DEEP_RESEARCH_DEPTH_PRESETS.some((item) => item.id === normalized)) return normalized;
  const numericPages = Number(pages || 0);
  if (numericPages >= 100) return "exhaustive";
  if (numericPages >= 50) return "comprehensive";
  if (numericPages >= 20) return "standard";
  return "brief";
}
function resolveDeepResearchDepthPreset(value, pages) {
  const mode = normalizeDeepResearchDepthMode(value, pages);
  return DEEP_RESEARCH_DEPTH_PRESETS.find((item) => item.id === mode) || DEEP_RESEARCH_DEPTH_PRESETS[1];
}
function ChatPanel({ fullWidth = false, hideHeader = false, studioMode = false, minimalStudio = false, studioAccessory = null }) {
  const { state: appState, dispatch: appDispatch, openFile, refreshModelInventory } = useApp();
  const api = window.kendrAPI;
  const [chat, dispatch] = reactExports.useReducer(chatReducer, void 0, () => ({ ...initChat, messages: loadHistory() }));
  const [input, setInput] = reactExports.useState("");
  const [resumeInput, setResumeInput] = reactExports.useState("");
  const [chatId, setChatId] = reactExports.useState(() => `chat-${Date.now()}`);
  const [dr, setDr] = reactExports.useState(DR_DEFAULTS);
  const [attachments, setAttachments] = reactExports.useState([]);
  const [researchKbs, setResearchKbs] = reactExports.useState([]);
  const [mcpEnabled, setMcpEnabled] = reactExports.useState(false);
  const [mcpServerCount, setMcpServerCount] = reactExports.useState(0);
  const [mcpUndiscovered, setMcpUndiscovered] = reactExports.useState(0);
  const [machineStatus, setMachineStatus] = reactExports.useState(null);
  const [machineStatusLoaded, setMachineStatusLoaded] = reactExports.useState(false);
  const [machineSyncRunning, setMachineSyncRunning] = reactExports.useState(false);
  const [diffPreviewPath, setDiffPreviewPath] = reactExports.useState("");
  const [showHistory, setShowHistory] = reactExports.useState(false);
  const [sessions, setSessions] = reactExports.useState(() => loadSessions());
  const [composerMenuOpen, setComposerMenuOpen] = reactExports.useState(false);
  const messagesEndRef = reactExports.useRef(null);
  const inputRef = reactExports.useRef(null);
  const composerMenuRef = reactExports.useRef(null);
  const esRef = reactExports.useRef(null);
  const resumeAttemptedRunRef = reactExports.useRef("");
  const staleRunRecoveryRef = reactExports.useRef("");
  const artifactRecoveryRef = reactExports.useRef(/* @__PURE__ */ new Set());
  const mirroredActivityIdsRef = reactExports.useRef([]);
  const apiBase = appState.backendUrl || "http://127.0.0.1:2151";
  const updateDr = (patch) => setDr((s) => ({ ...s, ...patch }));
  resolveDeepResearchDepthPreset(dr.depthMode, dr.pages);
  const selectedModelMeta = resolveSelectedModel(appState.selectedModel);
  const isSimpleStudioChat = studioMode && chat.mode === "chat";
  const modelInventory = appState.modelInventory;
  const deepResearchModelState = reactExports.useMemo(() => resolveDeepResearchModelSelection({
    requestedValue: dr.researchModel,
    inheritedValue: appState.selectedModel || "",
    modelInventory,
    webSearchEnabled: !!dr.webSearchEnabled
  }), [dr.researchModel, dr.webSearchEnabled, appState.selectedModel, modelInventory]);
  const deepResearchSearchProviderState = reactExports.useMemo(() => resolveDeepResearchSearchProviderSelection(
    buildDeepResearchSearchProviders(modelInventory),
    dr.searchBackend
  ), [dr.searchBackend, modelInventory]);
  const effectiveDeepResearchModel = deepResearchModelState.effectiveOption;
  const recommendedDeepResearchModel = deepResearchModelState.recommendedOption;
  const effectiveDeepResearchSearchProvider = deepResearchSearchProviderState.effective;
  reactExports.useEffect(() => {
    const effectiveId = effectiveDeepResearchSearchProvider?.id || "auto";
    const requestedId = dr.searchBackend || "auto";
    if (requestedId !== effectiveId) updateDr({ searchBackend: effectiveId });
  }, [dr.searchBackend, effectiveDeepResearchSearchProvider?.id]);
  const composerModelRaw = chat.mode === "research" ? effectiveDeepResearchModel?.value || appState.selectedModel || "" : appState.selectedModel || "";
  const composerModelMeta = resolveSelectedModel(composerModelRaw);
  const selectedModelAgentCapable = resolveAgentCapability(appState.selectedModel, modelInventory);
  const contextLimit = resolveContextWindow(composerModelRaw, modelInventory);
  const payloadPreview = reactExports.useMemo(() => {
    const draftText = String(input || "").trim();
    const body = buildPayload(
      draftText,
      chatId,
      "ctx-preview",
      appState.projectRoot,
      chat.mode,
      dr,
      attachments,
      studioMode,
      mcpEnabled
    );
    body.history = buildSimpleHistory(chat.messages, 14);
    const activePayloadModel = chat.mode === "research" ? effectiveDeepResearchModel : appState.selectedModel ? resolveSelectedModel(appState.selectedModel) : null;
    if (activePayloadModel) {
      const selected = activePayloadModel;
      if (selected.provider) body.provider = selected.provider;
      if (selected.model) body.model = selected.model;
    }
    if (chat.mode === "research" && effectiveDeepResearchModel?.model) {
      body.research_model = effectiveDeepResearchModel.model;
    }
    body.context_limit = contextLimit;
    if (isSimpleStudioChat) body.stream = true;
    return body;
  }, [input, chatId, appState.projectRoot, chat.mode, dr, attachments, studioMode, mcpEnabled, chat.messages, appState.selectedModel, isSimpleStudioChat, contextLimit, effectiveDeepResearchModel]);
  const estimatedContextTokens = estimateObjectTokens(payloadPreview);
  const contextPct = Math.min(100, Math.round(estimatedContextTokens / Math.max(contextLimit, 1) * 100));
  const stickyChecklistMsg = reactExports.useMemo(() => latestChecklistMessage(chat.messages), [chat.messages]);
  const stickyChecklist = Array.isArray(stickyChecklistMsg?.checklist) ? stickyChecklistMsg.checklist : [];
  const latestStreamingRunMsg = reactExports.useMemo(() => [...chat.messages || []].reverse().find((msg) => msg?.role === "assistant" && String(msg?.runId || "").trim() && isStreamingRunStatus(msg?.status)) || null, [chat.messages]);
  const activeRunId = String(chat.activeRunId || appState.activeRunId || latestStreamingRunMsg?.runId || "").trim();
  const awaitingRunId = String(chat.awaitingContext?.runId || "").trim();
  const stopTargetRunId = activeRunId || awaitingRunId;
  const composerRunActive = !chat.awaitingContext && !!activeRunId;
  const inlineAwaiting = shouldInlineAwaitingContext(chat.awaitingContext);
  const displayableAwaitingContext = hasDisplayableAwaitingContext(chat.awaitingContext);
  const hasMessages = chat.messages.length > 0;
  const showInlineAttachmentTools = !minimalStudio;
  const showInlineContextTools = !minimalStudio;
  const showInlineFlowStrip = !minimalStudio;
  const indexedResearchKbs = reactExports.useMemo(
    () => Array.isArray(researchKbs) ? researchKbs.filter((kb2) => String(kb2?.status || "").trim().toLowerCase() === "indexed") : [],
    [researchKbs]
  );
  const activeResearchKb = reactExports.useMemo(
    () => Array.isArray(researchKbs) ? researchKbs.find((kb2) => !!kb2?.is_active) || null : null,
    [researchKbs]
  );
  const selectedResearchKb = reactExports.useMemo(() => {
    if (!dr.kbEnabled) return null;
    if (dr.kbId) return indexedResearchKbs.find((kb2) => kb2.id === dr.kbId) || null;
    return activeResearchKb;
  }, [dr.kbEnabled, dr.kbId, indexedResearchKbs, activeResearchKb]);
  const deepResearchWorkflowRecommendation = reactExports.useMemo(() => {
    return resolveWorkflowRecommendation(modelInventory, "deep_research_report");
  }, [modelInventory]);
  const deepResearchWorkflowStageOptions = reactExports.useMemo(() => normalizeWorkflowStageOptions(deepResearchWorkflowRecommendation?.stage_options), [deepResearchWorkflowRecommendation]);
  const activeDeepResearchWorkflowCombo = reactExports.useMemo(() => {
    if (!dr.multiModelEnabled || !deepResearchWorkflowRecommendation) return null;
    const rawCombo = dr.multiModelStrategy === "cheapest" ? deepResearchWorkflowRecommendation.cheapest : deepResearchWorkflowRecommendation.best;
    return normalizeWorkflowCombo(rawCombo);
  }, [dr.multiModelEnabled, dr.multiModelStrategy, deepResearchWorkflowRecommendation]);
  const recommendedDeepResearchEvidenceStage = reactExports.useMemo(() => {
    if (!activeDeepResearchWorkflowCombo) return null;
    return activeDeepResearchWorkflowCombo.stages.find((stage) => stage?.stage === "evidence") || null;
  }, [activeDeepResearchWorkflowCombo]);
  reactExports.useEffect(() => {
    if (!dr.researchModel) return;
    if (!deepResearchModelState.requestedReason) return;
    setDr((current) => current.researchModel === dr.researchModel ? { ...current, researchModel: "" } : current);
  }, [dr.researchModel, deepResearchModelState.requestedReason]);
  const loadResearchKbs = reactExports.useCallback(async () => {
    try {
      const resp = await fetch(`${apiBase}/api/rag/kbs`);
      const data = await resp.json().catch(() => []);
      const next = Array.isArray(data) ? data : [];
      setResearchKbs(next);
      return next;
    } catch (_2) {
      setResearchKbs([]);
      return [];
    }
  }, [apiBase]);
  reactExports.useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const resp = await fetch(`${apiBase}/api/rag/kbs`);
        const data = await resp.json().catch(() => []);
        if (!cancelled) setResearchKbs(Array.isArray(data) ? data : []);
      } catch (_2) {
        if (!cancelled) setResearchKbs([]);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [apiBase]);
  const planKeywordsDetected = /\b(plan|roadmap|outline|steps|milestones|strategy)\b/i.test(input);
  const showPlanSuggestion = minimalStudio && selectedModelAgentCapable && !composerRunActive && chat.mode === "chat" && planKeywordsDetected;
  const showActiveWorkflowChip = minimalStudio && chat.mode !== "chat";
  const resolveArtifactActionUrl = reactExports.useCallback((item, runId, action = "download") => {
    const direct = String(
      action === "view" ? item?.viewUrl || item?.view_url || "" : item?.downloadUrl || item?.download_url || ""
    ).trim();
    if (direct) {
      try {
        return new URL(direct, apiBase || window.location.origin).toString();
      } catch (_2) {
        return direct;
      }
    }
    const resolvedRunId = String(runId || "").trim();
    const artifactName = String(item?.name || item?.label || basename$1(item?.path || "")).trim();
    if (!resolvedRunId || !artifactName) return "";
    const base = String(apiBase).replace(/\/$/, "");
    return `${base}/api/artifacts/${action}?run_id=${encodeURIComponent(resolvedRunId)}&name=${encodeURIComponent(artifactName)}`;
  }, [apiBase]);
  const openArtifact = reactExports.useCallback(async (item) => {
    const filePath = String(item?.path || "").trim();
    if (!filePath) return;
    appDispatch({ type: "SET_VIEW", view: "developer" });
    await openFile(filePath);
  }, [appDispatch, openFile]);
  const downloadArtifact = reactExports.useCallback((item, runId) => {
    const url = resolveArtifactActionUrl(item, runId, "download");
    if (!url) return;
    const link = document.createElement("a");
    link.href = url;
    const artifactName = String(item?.name || item?.label || "").trim();
    if (artifactName) link.setAttribute("download", artifactName);
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, [resolveArtifactActionUrl]);
  const reviewArtifact = reactExports.useCallback((item) => {
    const filePath = String(item?.path || "").trim();
    if (!filePath) return;
    setDiffPreviewPath(filePath);
  }, []);
  const clearActiveRunState = reactExports.useCallback(() => {
    dispatch({ type: "SET_STREAMING", val: false });
    dispatch({ type: "SET_RUN", id: null });
    appDispatch({ type: "SET_STREAMING", streaming: false });
    appDispatch({ type: "SET_ACTIVE_RUN", runId: null });
  }, [appDispatch]);
  reactExports.useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);
  reactExports.useEffect(() => {
    if (!appState.activeRunId) resumeAttemptedRunRef.current = "";
  }, [appState.activeRunId]);
  reactExports.useEffect(() => {
    if (!chat.awaitingContext || displayableAwaitingContext) return;
    dispatch({ type: "CLEAR_AWAITING" });
  }, [chat.awaitingContext, displayableAwaitingContext]);
  reactExports.useEffect(() => {
    const candidates = (chat.messages || []).filter((msg) => msg?.role === "assistant" && String(msg?.runId || "").trim() && !isPendingRunStatus(msg?.status) && (!Array.isArray(msg?.artifacts) || !hasReportArtifacts(msg.artifacts)));
    if (!candidates.length) return;
    let cancelled = false;
    (async () => {
      for (const msg of candidates.slice(-8)) {
        const runId = String(msg.runId || "").trim();
        if (!runId || artifactRecoveryRef.current.has(runId)) continue;
        try {
          let recoveredArtifacts = [];
          let runSnapshot = {};
          const resp = await fetch(`${apiBase}/api/runs/${encodeURIComponent(runId)}`);
          runSnapshot = await resp.json().catch(() => ({}));
          if (cancelled) return;
          if (resp.ok) recoveredArtifacts = runSnapshotArtifacts(runSnapshot);
          if (!recoveredArtifacts.length) {
            const artifactResp = await fetch(`${apiBase}/api/runs/${encodeURIComponent(runId)}/artifacts`);
            const artifactData = await artifactResp.json().catch(() => ({}));
            if (cancelled) return;
            if (artifactResp.ok && Array.isArray(artifactData?.files)) {
              recoveredArtifacts = artifactData.files;
            }
          }
          if (!recoveredArtifacts.length) continue;
          if (Array.isArray(msg?.artifacts) && msg.artifacts.length) {
            recoveredArtifacts = [...msg.artifacts, ...recoveredArtifacts];
          }
          artifactRecoveryRef.current.add(runId);
          dispatch({
            type: "UPD_MSG",
            id: msg.id,
            patch: {
              ...runSnapshotMessageMeta(runSnapshot),
              artifacts: recoveredArtifacts
            }
          });
        } catch (_2) {
          continue;
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chat.messages, apiBase]);
  reactExports.useEffect(() => {
    const staleAwaiting = (chat.messages || []).filter((msg) => msg?.role === "assistant" && String(msg?.status || "").trim().toLowerCase() === "awaiting" && String(msg?.runId || "").trim() && !messageHasConcreteAwaitingPrompt(msg));
    if (!staleAwaiting.length) return;
    for (const msg of staleAwaiting) {
      const status = String(msg.lastKnownRunStatus || "").trim().toLowerCase();
      const snapshot = {
        status: status || "running",
        run_id: msg.runId,
        started_at: msg.runStartedAt,
        run_output_dir: msg.runOutputDir,
        log_paths: msg.executionLogPath ? { execution_log: msg.executionLogPath } : {},
        last_error: msg.lastError,
        final_output: msg.content
      };
      const patch = ACTIVE_RUN_STATUSES.has(status) || !status ? buildRunningMessagePatch(snapshot, msg) : status === "awaiting_user_input" ? buildInvalidAwaitingErrorPatch(snapshot, msg.runId, msg) : status === "completed" ? buildCompletedMessagePatch(snapshot, msg) : buildFailedMessagePatch(snapshot, msg.runId, status || "failed", msg);
      dispatch({ type: "UPD_MSG", id: msg.id, patch });
    }
  }, [chat.messages]);
  reactExports.useEffect(() => {
    if (chat.streaming || appState.activeRunId) return;
    const pendingMsg = [...chat.messages || []].reverse().find((msg) => msg?.role === "assistant" && String(msg?.runId || "").trim() && isPendingRunStatus(msg?.status));
    if (!pendingMsg) {
      staleRunRecoveryRef.current = "";
      return;
    }
    const runId = String(pendingMsg.runId || "").trim();
    const recoveryKey = `${pendingMsg.id}:${runId}:${pendingMsg.status || ""}`;
    if (!runId || staleRunRecoveryRef.current === recoveryKey) return;
    staleRunRecoveryRef.current = recoveryKey;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${apiBase}/api/runs/${encodeURIComponent(runId)}`);
        const data = await resp.json().catch(() => ({}));
        if (cancelled) return;
        if (!resp.ok) {
          dispatch({
            type: "UPD_MSG",
            id: pendingMsg.id,
            patch: {
              status: "error",
              statusText: "",
              content: pendingMsg.lastError || failureMessageForRecoveredRun(runId)
            }
          });
          clearActiveRunState();
          return;
        }
        dispatch({
          type: "UPD_MSG",
          id: pendingMsg.id,
          patch: {
            ...runSnapshotMessageMeta(data),
            runStartedAt: data?.started_at || pendingMsg.runStartedAt || (/* @__PURE__ */ new Date()).toISOString()
          }
        });
        const status = runSnapshotStatus(data);
        if (ACTIVE_RUN_STATUSES.has(status)) {
          dispatch({
            type: "UPD_MSG",
            id: pendingMsg.id,
            patch: {
              ...buildRunningMessagePatch(data, pendingMsg),
              runStartedAt: data?.started_at || pendingMsg.runStartedAt || (/* @__PURE__ */ new Date()).toISOString()
            }
          });
          dispatch({ type: "CLEAR_AWAITING" });
          dispatch({ type: "SET_RUN", id: runId });
          appDispatch({ type: "SET_ACTIVE_RUN", runId });
          appDispatch({ type: "SET_STREAMING", streaming: true });
          return;
        }
        if (status === "awaiting_user_input") {
          const awaitingPatch = buildAwaitingState(data, pendingMsg);
          if (!awaitingPatch) {
            dispatch({
              type: "UPD_MSG",
              id: pendingMsg.id,
              patch: buildInvalidAwaitingErrorPatch(data, runId, pendingMsg)
            });
            dispatch({ type: "CLEAR_AWAITING" });
            return;
          }
          dispatch({
            type: "UPD_MSG",
            id: pendingMsg.id,
            patch: {
              runStartedAt: data?.started_at || pendingMsg.runStartedAt || (/* @__PURE__ */ new Date()).toISOString(),
              ...awaitingPatch
            }
          });
          return;
        }
        dispatch({
          type: "UPD_MSG",
          id: pendingMsg.id,
          patch: status === "completed" ? buildCompletedMessagePatch(data, pendingMsg) : buildFailedMessagePatch(data, runId, status, pendingMsg)
        });
        dispatch({ type: "CLEAR_AWAITING" });
        clearActiveRunState();
      } catch (_2) {
        if (cancelled) return;
        dispatch({
          type: "UPD_MSG",
          id: pendingMsg.id,
          patch: {
            status: "error",
            statusText: "",
            content: pendingMsg.lastError || failureMessageForRecoveredRun(runId)
          }
        });
        dispatch({ type: "CLEAR_AWAITING" });
        clearActiveRunState();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chat.messages, chat.streaming, appState.activeRunId, apiBase, appDispatch, clearActiveRunState]);
  reactExports.useEffect(() => {
    if ((chat.mode === "agent" || chat.mode === "plan") && !selectedModelAgentCapable) {
      dispatch({ type: "SET_MODE", mode: "chat" });
    }
  }, [chat.mode, selectedModelAgentCapable]);
  reactExports.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.messages]);
  reactExports.useEffect(() => {
    if (!composerMenuOpen) return void 0;
    const onMouseDown = (event) => {
      if (composerMenuRef.current && !composerMenuRef.current.contains(event.target)) setComposerMenuOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [composerMenuOpen]);
  reactExports.useEffect(() => {
    if (composerRunActive) setComposerMenuOpen(false);
  }, [composerRunActive]);
  reactExports.useEffect(() => {
    const entries = chat.messages.filter(shouldMirrorActivityMessage).map((msg) => buildActivityEntry(msg, { id: `studio:${msg.id}`, source: studioMode ? "studio" : "chat" })).filter(Boolean);
    const nextIds = new Set(entries.map((entry) => entry.id));
    for (const entry of entries) {
      appDispatch({ type: "UPSERT_ACTIVITY_ENTRY", entry });
    }
    const removedIds = mirroredActivityIdsRef.current.filter((id2) => !nextIds.has(id2));
    if (removedIds.length) {
      appDispatch({ type: "REMOVE_ACTIVITY_ENTRIES", ids: removedIds });
    }
    mirroredActivityIdsRef.current = Array.from(nextIds);
  }, [chat.messages, appDispatch, studioMode]);
  reactExports.useEffect(() => {
    saveHistory(chat.messages);
  }, [chat.messages]);
  reactExports.useEffect(() => {
    refreshModelInventory(false);
  }, [refreshModelInventory]);
  reactExports.useEffect(() => {
    const days = appState.settings?.chatHistoryRetentionDays ?? 14;
    setSessions((prev) => {
      const pruned = pruneOldSessions(prev, days);
      if (pruned.length !== prev.length) saveSessions(pruned);
      return pruned;
    });
  }, [appState.settings?.chatHistoryRetentionDays]);
  const saveCurrentSession = reactExports.useCallback(() => {
    if (chat.messages.length === 0) return;
    const session = {
      id: chatId,
      title: makeSessionTitle(chat.messages),
      createdAt: String(chat.messages[0]?.ts || (/* @__PURE__ */ new Date()).toISOString()),
      updatedAt: (/* @__PURE__ */ new Date()).toISOString(),
      messages: chat.messages
    };
    const days = appState.settings?.chatHistoryRetentionDays ?? 14;
    setSessions((prev) => {
      const updated = pruneOldSessions([...prev.filter((s) => s.id !== chatId), session], days);
      saveSessions(updated);
      return updated;
    });
  }, [chat.messages, chatId, appState.settings?.chatHistoryRetentionDays]);
  const newChat = reactExports.useCallback(() => {
    saveCurrentSession();
    dispatch({ type: "CLEAR" });
    saveHistory([]);
    setShowHistory(false);
    setAttachments([]);
    setResumeInput("");
    setChatId(`chat-${Date.now()}`);
  }, [saveCurrentSession]);
  const compactContext = reactExports.useCallback(async () => {
    if (!chat.messages.length || composerRunActive) return;
    saveCurrentSession();
    try {
      const resp = await fetch(`${apiBase}/api/chat/compact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel: "webchat",
          sender_id: "desktop_user",
          chat_id: chatId,
          history: buildSimpleHistory(chat.messages, 200),
          context_limit: contextLimit
        })
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.error) throw new Error(data.error || data.detail || resp.statusText);
      const note = {
        id: `c-${Date.now()}`,
        role: "assistant",
        content: `Context compacted into ${data.summary_file || "summary.md"} (${Number(data.summary_tokens || 0).toLocaleString()} tokens, level ${data.compaction_level || 0}).`,
        status: "done",
        mode: "chat",
        modeLabel: "Compacted",
        ts: /* @__PURE__ */ new Date()
      };
      dispatch({ type: "ADD_MSG", msg: note });
      saveHistory([...chat.messages, note]);
      setShowHistory(false);
    } catch (err) {
      const note = {
        id: `c-${Date.now()}`,
        role: "assistant",
        content: `Context compaction failed: ${err.message}`,
        status: "error",
        mode: "chat",
        modeLabel: "Compacted",
        ts: /* @__PURE__ */ new Date()
      };
      dispatch({ type: "ADD_MSG", msg: note });
      saveHistory([...chat.messages, note]);
    }
  }, [apiBase, chat.messages, composerRunActive, chatId, contextLimit, saveCurrentSession]);
  const loadSession = reactExports.useCallback((session) => {
    esRef.current?.close();
    saveCurrentSession();
    const msgs = session.messages.map((m2) => ({ ...m2, ts: new Date(m2.ts) }));
    dispatch({ type: "LOAD_MSGS", messages: msgs });
    dispatch({ type: "SET_STREAMING", val: false });
    appDispatch({ type: "SET_STREAMING", streaming: false });
    saveHistory(msgs);
    setShowHistory(false);
  }, [saveCurrentSession, appDispatch]);
  const deleteSession = reactExports.useCallback((id2) => {
    setSessions((prev) => {
      const updated = prev.filter((s) => s.id !== id2);
      saveSessions(updated);
      return updated;
    });
  }, []);
  reactExports.useEffect(() => {
    if (chat.mode === "agent" || chat.mode === "plan") setMcpEnabled(true);
  }, [chat.mode]);
  reactExports.useEffect(() => {
    fetch(`${apiBase}/api/mcp/servers`).then((r2) => r2.ok ? r2.json() : []).then((data) => {
      const servers = Array.isArray(data) ? data : data.servers || [];
      const enabled = servers.filter((s) => s.enabled !== false);
      setMcpServerCount(enabled.length);
      setMcpUndiscovered(enabled.filter((s) => !s.tool_count || s.tool_count === 0).length);
    }).catch(() => {
    });
  }, [apiBase, mcpEnabled]);
  const syncWorkingDirectory = (appState.projectRoot || appState.settings?.projectRoot || "").trim();
  const fetchMachineStatus = reactExports.useCallback(async () => {
    try {
      const q2 = syncWorkingDirectory ? `?working_directory=${encodeURIComponent(syncWorkingDirectory)}` : "";
      const resp = await fetch(`${apiBase}/api/machine/status${q2}`);
      if (!resp.ok) {
        setMachineStatusLoaded(true);
        return null;
      }
      const data = await resp.json().catch(() => ({}));
      const status = data?.status && typeof data.status === "object" ? data.status : null;
      if (status) setMachineStatus(status);
      setMachineStatusLoaded(true);
      return status;
    } catch (_2) {
      setMachineStatusLoaded(true);
      return null;
    }
  }, [apiBase, syncWorkingDirectory]);
  const triggerMachineSync = reactExports.useCallback(async (scope = "machine", isAuto = false) => {
    if (machineSyncRunning) return;
    setMachineSyncRunning(true);
    try {
      const resp = await fetch(`${apiBase}/api/machine/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope,
          working_directory: syncWorkingDirectory || void 0
        })
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data?.status && typeof data.status === "object") {
        setMachineStatus(data.status);
        if (api?.settings?.set) {
          const nowIso = (/* @__PURE__ */ new Date()).toISOString();
          await api.settings.set("machineLastAutoSyncAt", nowIso);
          appDispatch({ type: "SET_SETTINGS", settings: { machineLastAutoSyncAt: nowIso } });
        }
      }
    } catch (_2) {
    } finally {
      setMachineSyncRunning(false);
      if (!isAuto) fetchMachineStatus();
    }
  }, [apiBase, syncWorkingDirectory, machineSyncRunning, api, appDispatch, fetchMachineStatus]);
  reactExports.useEffect(() => {
    fetchMachineStatus();
  }, [fetchMachineStatus]);
  reactExports.useEffect(() => {
    const id2 = setInterval(() => {
      fetchMachineStatus();
    }, 60 * 1e3);
    return () => clearInterval(id2);
  }, [fetchMachineStatus]);
  reactExports.useEffect(() => {
    const enabled = !!appState.settings?.machineAutoSyncEnabled;
    if (!enabled) return;
    if (machineSyncRunning) return;
    const intervalDays = Math.max(1, Math.min(30, Number(appState.settings?.machineAutoSyncIntervalDays || 7)));
    const lastRaw = String(appState.settings?.machineLastAutoSyncAt || "").trim();
    const lastTs = lastRaw ? Date.parse(lastRaw) : 0;
    const dueMs = intervalDays * 24 * 60 * 60 * 1e3;
    const now = Date.now();
    if (!lastTs || Number.isNaN(lastTs) || now - lastTs >= dueMs) {
      triggerMachineSync("machine", true);
    }
  }, [appState.settings, machineSyncRunning, triggerMachineSync]);
  const send = reactExports.useCallback(async (text, isResume = false) => {
    const msg = (typeof text === "string" ? text.trim() : "") || input.trim();
    if (!msg || composerRunActive) return;
    if (!isResume && chat.mode === "research" && dr.kbEnabled) {
      if (!researchKbs.length) {
        window.alert("No knowledge bases found. Create and index one in Super-RAG or `kendr rag` first.");
        return;
      }
      const targetKb = dr.kbId ? researchKbs.find((kb2) => kb2.id === dr.kbId) : activeResearchKb;
      if (!targetKb) {
        window.alert("No active indexed knowledge base is available. Select an indexed KB or set one active in Super-RAG.");
        return;
      }
      if (String(targetKb.status || "").trim().toLowerCase() !== "indexed") {
        window.alert(`Knowledge base "${targetKb.name || targetKb.id}" is not indexed yet.`);
        return;
      }
    }
    setInput("");
    setResumeInput("");
    const runId = `ui-${Date.now().toString(36)}`;
    const userMsgId = `u-${runId}`;
    const currentAwaitingContext = chat.awaitingContext || null;
    const resumeMessageId = String(currentAwaitingContext?.messageId || "").trim();
    const preserveAwaitingBubble = isResume && resumeMessageId && shouldInlineAwaitingContext(currentAwaitingContext);
    const asstMsgId = isResume && resumeMessageId && !preserveAwaitingBubble ? resumeMessageId : `a-${runId}`;
    const currentMode = chat.mode;
    const currentModeLabel = modeLabel(currentMode);
    const sentAttachments = Array.isArray(attachments) ? attachments.map((item) => ({ ...item })) : [];
    dispatch({
      type: "ADD_MSG",
      msg: {
        id: userMsgId,
        role: "user",
        content: msg,
        attachments: sentAttachments,
        mode: currentMode,
        modeLabel: currentModeLabel,
        ts: /* @__PURE__ */ new Date()
      }
    });
    dispatch({ type: "SET_STREAMING", val: true });
    dispatch({ type: "SET_RUN", id: runId });
    dispatch({ type: "CLEAR_AWAITING" });
    setAttachments([]);
    if (preserveAwaitingBubble && resumeMessageId) {
      const normalizedReply = msg.toLowerCase();
      const approvalState = normalizedReply === "approve" ? "approved" : normalizedReply === "cancel" ? "rejected" : "suggested";
      dispatch({
        type: "UPD_MSG",
        id: resumeMessageId,
        patch: {
          status: "done",
          approvalState
        }
      });
    }
    if (isResume && resumeMessageId && !preserveAwaitingBubble) {
      dispatch({
        type: "UPD_MSG",
        id: asstMsgId,
        patch: {
          content: "",
          status: "thinking",
          runId: isSimpleStudioChat ? null : runId,
          runStartedAt: (/* @__PURE__ */ new Date()).toISOString(),
          logs: [],
          mode: currentMode,
          modeLabel: currentModeLabel,
          statusText: "Continuing approved plan...",
          approvalScope: "",
          approvalKind: "",
          approvalRequest: null,
          awaitingDecision: "",
          approvalState: ""
        }
      });
    } else {
      dispatch({
        type: "ADD_MSG",
        msg: {
          id: asstMsgId,
          role: "assistant",
          content: "",
          steps: [],
          progress: [],
          logs: [],
          checklist: [],
          status: "thinking",
          runId: isSimpleStudioChat ? null : runId,
          runStartedAt: (/* @__PURE__ */ new Date()).toISOString(),
          mode: currentMode,
          modeLabel: currentModeLabel,
          approvalScope: "",
          approvalKind: "",
          approvalRequest: null,
          awaitingDecision: "",
          approvalState: "",
          ts: /* @__PURE__ */ new Date()
        }
      });
    }
    appDispatch({ type: "SET_STREAMING", streaming: true });
    try {
      const endpoint = isResume && currentAwaitingContext ? `${apiBase}/api/chat/resume` : isSimpleStudioChat ? `${apiBase}/api/chat/simple` : `${apiBase}/api/chat`;
      const body = isResume && currentAwaitingContext ? {
        run_id: currentAwaitingContext.runId,
        workflow_id: currentAwaitingContext.workflowId,
        text: msg,
        channel: "webchat"
      } : buildPayload(msg, chatId, runId, appState.projectRoot, chat.mode, dr, sentAttachments, studioMode, mcpEnabled);
      const activePayloadModel = !isResume ? chat.mode === "research" ? effectiveDeepResearchModel : appState.selectedModel ? resolveSelectedModel(appState.selectedModel) : null : null;
      if (!isResume && activePayloadModel) {
        const selected = activePayloadModel;
        if (selected.provider) body.provider = selected.provider;
        if (selected.model) body.model = selected.model;
      }
      if (!isResume && chat.mode === "research" && effectiveDeepResearchModel?.model) {
        body.research_model = effectiveDeepResearchModel.model;
      }
      if (!isResume) {
        body.history = buildSimpleHistory(chat.messages, 14);
        body.context_limit = contextLimit;
      }
      if (isSimpleStudioChat && !isResume) {
        body.stream = true;
        const resp2 = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });
        const data = await resp2.json().catch(() => ({}));
        if (!resp2.ok) {
          refreshModelInventory(true);
          dispatch({ type: "UPD_MSG", id: asstMsgId, patch: { content: data.error || data.detail || resp2.statusText, status: "error", runId: null } });
          clearActiveRunState();
          return;
        }
        if (data.streaming) {
          const effectiveRunId2 = data.run_id || runId;
          dispatch({ type: "UPD_MSG", id: asstMsgId, patch: { runId: effectiveRunId2, status: "thinking" } });
          dispatch({ type: "SET_RUN", id: effectiveRunId2 });
          appDispatch({ type: "SET_ACTIVE_RUN", runId: effectiveRunId2 });
          openStream(effectiveRunId2, asstMsgId);
          return;
        } else {
          dispatch({ type: "UPD_MSG", id: asstMsgId, patch: { content: data.answer || "", status: "done", runId: null, artifacts: [] } });
          clearActiveRunState();
          return;
        }
      }
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        refreshModelInventory(true);
        dispatch({ type: "UPD_MSG", id: asstMsgId, patch: { content: err.error || err.detail || resp.statusText, status: "error" } });
        clearActiveRunState();
        return;
      }
      const { run_id: srvRunId } = await resp.json().catch(() => ({}));
      const effectiveRunId = srvRunId || runId;
      dispatch({ type: "UPD_MSG", id: asstMsgId, patch: { runId: effectiveRunId, status: "thinking" } });
      dispatch({ type: "SET_RUN", id: effectiveRunId });
      appDispatch({ type: "SET_ACTIVE_RUN", runId: effectiveRunId });
      openStream(effectiveRunId, asstMsgId);
    } catch (err) {
      refreshModelInventory(true);
      dispatch({ type: "UPD_MSG", id: asstMsgId, patch: { content: `Cannot reach backend: ${err.message}`, status: "error" } });
      clearActiveRunState();
    }
  }, [input, composerRunActive, chat.awaitingContext, chat.mode, apiBase, appState.projectRoot, appState.selectedModel, chatId, dr, attachments, studioMode, isSimpleStudioChat, mcpEnabled, appDispatch, refreshModelInventory, contextLimit, researchKbs, activeResearchKb, clearActiveRunState]);
  const openStream = reactExports.useCallback((runId, asstMsgId) => {
    esRef.current?.close();
    const es = new EventSource(`${apiBase}/api/stream?run_id=${encodeURIComponent(runId)}`);
    let stepCounter = 0;
    let closed = false;
    let statusPollTimer = null;
    const existingMsg = (chat.messages || []).find((msg) => msg?.id === asstMsgId || String(msg?.runId || "").trim() === runId);
    const seenLogSignatures = new Set(
      (Array.isArray(existingMsg?.logs) ? existingMsg.logs : []).map((item) => buildExecutionLogSignature(item)).filter(Boolean)
    );
    const fallback = {
      transportErrored: false,
      syncingFile: false,
      logPath: "",
      logContentLength: 0,
      logMtime: 0,
      logBuffer: "",
      parserState: {}
    };
    const closeClean = () => {
      if (closed) return;
      closed = true;
      if (statusPollTimer) window.clearInterval(statusPollTimer);
      es.close();
      if (esRef.current?.close === closeClean) esRef.current = null;
    };
    esRef.current = { close: closeClean };
    const finishStream = () => {
      closeClean();
      clearActiveRunState();
    };
    const pushLogEntry = (item) => {
      const text = String(item?.text || "").trim();
      if (!text) return false;
      const entry = {
        id: String(item?.id || `log-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`),
        ts: String(item?.ts || item?.timestamp || (/* @__PURE__ */ new Date()).toISOString()),
        clock: String(item?.clock || executionLogClockLabel(item?.ts || item?.timestamp || "")).trim(),
        text,
        category: String(item?.category || "info").trim() || "info"
      };
      const signature = buildExecutionLogSignature(entry);
      if (signature && seenLogSignatures.has(signature)) return false;
      if (signature) seenLogSignatures.add(signature);
      dispatch({ type: "ADD_LOG_ENTRY", msgId: asstMsgId, item: entry });
      dispatch({
        type: "UPD_MSG",
        id: asstMsgId,
        patch: {
          status: "streaming",
          statusText: text
        }
      });
      return true;
    };
    const applyRunSnapshot = (snapshot, fallbackStatus = "") => {
      if (closed) return;
      const data = snapshot && typeof snapshot === "object" ? snapshot : {};
      const status = runSnapshotStatus(data, fallbackStatus);
      if (status === "awaiting_user_input") {
        const awaitingPatch = buildAwaitingState(data, existingMsg || {});
        if (!awaitingPatch) {
          dispatch({
            type: "UPD_MSG",
            id: asstMsgId,
            patch: buildInvalidAwaitingErrorPatch(data, runId, existingMsg || {})
          });
          dispatch({ type: "CLEAR_AWAITING" });
          finishStream();
          return;
        }
        dispatch({
          type: "SET_AWAITING",
          ctx: buildAwaitingContext(data, runId, asstMsgId, awaitingPatch)
        });
        dispatch({
          type: "UPD_MSG",
          id: asstMsgId,
          patch: {
            ...runSnapshotMessageMeta(data),
            ...awaitingPatch,
            artifacts: runSnapshotArtifacts(data),
            checklist: runSnapshotChecklist(data)
          }
        });
        finishStream();
        return;
      }
      dispatch({
        type: "UPD_MSG",
        id: asstMsgId,
        patch: status === "completed" ? buildCompletedMessagePatch(data, existingMsg || {}) : buildFailedMessagePatch(data, runId, status, existingMsg || {})
      });
      dispatch({ type: "CLEAR_AWAITING" });
      finishStream();
    };
    const syncExecutionLogFromFile = async (logPath) => {
      const fileApi = window.kendrAPI?.fs;
      if (closed || !fileApi?.readFile) return;
      const targetPath = String(logPath || "").trim();
      if (!targetPath || fallback.syncingFile) return;
      if (targetPath !== fallback.logPath) {
        fallback.logPath = targetPath;
        fallback.logContentLength = 0;
        fallback.logMtime = 0;
        fallback.logBuffer = "";
        fallback.parserState = {};
      }
      fallback.syncingFile = true;
      try {
        if (fileApi?.stat) {
          const stats = await fileApi.stat(targetPath);
          const nextSize = Number(stats?.size || 0);
          const nextMtime = Number(stats?.mtime || 0);
          if (!stats?.error && nextSize === fallback.logContentLength && nextMtime === fallback.logMtime) return;
          if (!stats?.error && nextSize < fallback.logContentLength) {
            fallback.logContentLength = 0;
            fallback.logMtime = 0;
            fallback.logBuffer = "";
            fallback.parserState = {};
          }
        }
        const result = await fileApi.readFile(targetPath);
        if (result?.error) return;
        const content = String(result?.content || "");
        if (closed || !content) return;
        if (content.length < fallback.logContentLength) {
          fallback.logContentLength = 0;
          fallback.logMtime = 0;
          fallback.logBuffer = "";
          fallback.parserState = {};
        }
        if (content.length === fallback.logContentLength) return;
        const delta = content.slice(fallback.logContentLength);
        fallback.logContentLength = content.length;
        if (fileApi?.stat) {
          const stats = await fileApi.stat(targetPath);
          if (!stats?.error) fallback.logMtime = Number(stats?.mtime || fallback.logMtime || 0);
        }
        fallback.logBuffer += delta;
        const lines = fallback.logBuffer.split(/\r?\n/);
        fallback.logBuffer = lines.pop() || "";
        for (const line of lines) {
          const entry = parseExecutionLogLine(line, fallback.parserState);
          if (entry) pushLogEntry(entry);
        }
      } catch (_2) {
      } finally {
        fallback.syncingFile = false;
      }
    };
    const refreshRunSnapshot = async () => {
      if (closed) return;
      try {
        const resp = await fetch(`${apiBase}/api/runs/${encodeURIComponent(runId)}`);
        const data = await resp.json().catch(() => ({}));
        if (closed) return;
        if (!resp.ok) {
          dispatch({
            type: "UPD_MSG",
            id: asstMsgId,
            patch: buildFailedMessagePatch(data, runId, "failed", existingMsg || {})
          });
          dispatch({ type: "CLEAR_AWAITING" });
          finishStream();
          return;
        }
        dispatch({
          type: "UPD_MSG",
          id: asstMsgId,
          patch: {
            ...runSnapshotMessageMeta(data)
          }
        });
        const logPath = resolveRunSnapshotLogPath(data);
        if (logPath) await syncExecutionLogFromFile(logPath);
        const status = runSnapshotStatus(data);
        if (TERMINAL_RUN_STATUSES.has(status) || status === "awaiting_user_input") {
          applyRunSnapshot(data, status);
          return;
        }
        if (ACTIVE_RUN_STATUSES.has(status)) {
          dispatch({
            type: "UPD_MSG",
            id: asstMsgId,
            patch: {
              ...buildRunningMessagePatch(data, {
                ...existingMsg || {},
                statusText: fallback.transportErrored ? "Reconnected to background run. Checking execution log..." : existingMsg?.statusText
              })
            }
          });
          dispatch({ type: "CLEAR_AWAITING" });
          fallback.transportErrored = false;
        }
      } catch (_2) {
      }
    };
    statusPollTimer = window.setInterval(() => {
      refreshRunSnapshot();
    }, 2e3);
    refreshRunSnapshot();
    es.addEventListener("status", (e) => {
      try {
        const d = JSON.parse(e.data);
        if (d.status && d.status !== "connected") {
          fallback.transportErrored = false;
          dispatch({ type: "UPD_MSG", id: asstMsgId, patch: { statusText: sanitizeStatusMessage(d.message || d.status) } });
          dispatch({
            type: "ADD_PROGRESS",
            msgId: asstMsgId,
            item: {
              id: "runtime-status",
              slot: "runtime-status",
              title: "Runtime update",
              detail: sanitizeStatusMessage(d.message || d.status || ""),
              kind: "status",
              status: d.status || "running"
            }
          });
        }
      } catch (_2) {
      }
    });
    es.addEventListener("step", (e) => {
      try {
        const step = JSON.parse(e.data);
        const stepId = step.step_id || step.id || `step-${++stepCounter}`;
        dispatch({
          type: "ADD_STEP",
          msgId: asstMsgId,
          step: {
            stepId,
            agent: step.agent || step.name || "agent",
            status: step.status || "running",
            message: step.message || "",
            reason: step.reason || "",
            durationLabel: step.duration_label || "",
            startedAt: step.started_at || ""
          }
        });
        const agent = String(step.agent || step.name || "agent").trim();
        const reason = String(step.reason || step.message || "").trim();
        const stepStatus = String(step.status || "running").toLowerCase();
        const title = ["completed", "done", "success"].includes(stepStatus) ? `${agent} completed a task` : ["failed", "error"].includes(stepStatus) ? `${agent} reported a failure` : `${agent} is working`;
        dispatch({
          type: "ADD_PROGRESS",
          msgId: asstMsgId,
          item: {
            id: stepId,
            title,
            detail: reason || "",
            kind: "step",
            status: step.status || "running"
          }
        });
        dispatch({ type: "UPD_MSG", id: asstMsgId, patch: { status: "streaming" } });
      } catch (_2) {
      }
    });
    es.addEventListener("activity", (e) => {
      try {
        const item = JSON.parse(e.data);
        const title = String(item.title || item.kind || "Activity").trim();
        const detail = String(item.detail || item.command || "").trim();
        dispatch({
          type: "ADD_PROGRESS",
          msgId: asstMsgId,
          item: {
            id: item.id || `activity-${Date.now()}`,
            title,
            detail,
            kind: item.kind || "activity",
            status: item.status || "running",
            command: item.command || "",
            cwd: item.cwd || "",
            actor: item.actor || "",
            durationLabel: item.duration_label || "",
            exitCode: item.exit_code
          }
        });
      } catch (_2) {
      }
    });
    es.addEventListener("log", (e) => {
      try {
        const item = JSON.parse(e.data);
        fallback.transportErrored = false;
        pushLogEntry({
          id: item.id || `log-${Date.now()}`,
          ts: item.timestamp || (/* @__PURE__ */ new Date()).toISOString(),
          clock: item.clock || "",
          text: item.text || "",
          category: item.category || "info"
        });
      } catch (_2) {
      }
    });
    es.addEventListener("delta", (e) => {
      try {
        const d = JSON.parse(e.data);
        if (!d.delta) return;
        fallback.transportErrored = false;
        dispatch({ type: "APPEND_MSG_CONTENT", id: asstMsgId, delta: String(d.delta) });
        dispatch({ type: "UPD_MSG", id: asstMsgId, patch: { status: "streaming" } });
      } catch (_2) {
      }
    });
    es.addEventListener("result", (e) => {
      try {
        const d = JSON.parse(e.data);
        const awaitingSignal = runSnapshotSignalsAwaiting(d);
        if (awaitingSignal) {
          const awaitingSnapshot = { ...d, status: "awaiting_user_input", run_id: runId };
          const awaitingPatch = buildAwaitingState(awaitingSnapshot, existingMsg || {});
          if (!awaitingPatch) {
            dispatch({
              type: "UPD_MSG",
              id: asstMsgId,
              patch: buildInvalidAwaitingRunningPatch(
                { ...d, status: "running", run_id: runId },
                existingMsg || {}
              )
            });
            dispatch({ type: "CLEAR_AWAITING" });
            refreshRunSnapshot();
            return;
          }
          dispatch({
            type: "SET_AWAITING",
            ctx: buildAwaitingContext(awaitingSnapshot, runId, asstMsgId, awaitingPatch)
          });
          dispatch({
            type: "UPD_MSG",
            id: asstMsgId,
            patch: {
              ...runSnapshotMessageMeta(awaitingSnapshot),
              ...awaitingPatch,
              artifacts: d.artifact_files || [],
              checklist: runSnapshotChecklist(d)
            }
          });
          return;
        }
        dispatch({
          type: "UPD_MSG",
          id: asstMsgId,
          patch: buildCompletedMessagePatch({ ...d, status: "completed", run_id: runId }, existingMsg || {})
        });
        dispatch({ type: "CLEAR_AWAITING" });
      } catch (_2) {
      }
    });
    es.addEventListener("done", (e) => {
      let shouldFinish = true;
      try {
        const d = JSON.parse(e.data);
        const awaitingSignal = runSnapshotSignalsAwaiting(d);
        if (awaitingSignal) {
          const awaitingSnapshot = { ...d, status: "awaiting_user_input", run_id: runId };
          const awaitingPatch = buildAwaitingState(awaitingSnapshot, existingMsg || {});
          if (!awaitingPatch) {
            dispatch({
              type: "UPD_MSG",
              id: asstMsgId,
              patch: buildInvalidAwaitingRunningPatch(
                { ...d, status: "running", run_id: runId },
                existingMsg || {}
              )
            });
            dispatch({ type: "CLEAR_AWAITING" });
            shouldFinish = false;
            refreshRunSnapshot();
            return;
          }
          dispatch({
            type: "SET_AWAITING",
            ctx: buildAwaitingContext(awaitingSnapshot, runId, asstMsgId, awaitingPatch)
          });
          dispatch({
            type: "UPD_MSG",
            id: asstMsgId,
            patch: {
              ...runSnapshotMessageMeta(awaitingSnapshot),
              ...awaitingPatch
            }
          });
          return;
        }
        const normalized = runSnapshotStatus({ ...d, run_id: runId });
        dispatch({
          type: "UPD_MSG",
          id: asstMsgId,
          patch: normalized === "completed" ? buildCompletedMessagePatch({ ...d, status: "completed", run_id: runId }, existingMsg || {}) : buildFailedMessagePatch({ ...d, status: normalized, run_id: runId }, runId, normalized, existingMsg || {})
        });
        dispatch({ type: "CLEAR_AWAITING" });
      } catch (_2) {
      }
      if (shouldFinish) finishStream();
    });
    es.addEventListener("error", (e) => {
      const payload = String(e?.data || "").trim();
      if (!payload) return;
      try {
        const d = JSON.parse(payload);
        dispatch({
          type: "UPD_MSG",
          id: asstMsgId,
          patch: {
            ...runSnapshotMessageMeta({ ...d, status: "failed", run_id: runId }),
            content: d.message || "Run failed.",
            status: "error"
          }
        });
      } catch (_2) {
        dispatch({
          type: "UPD_MSG",
          id: asstMsgId,
          patch: {
            ...runSnapshotMessageMeta({ status: "failed", run_id: runId }),
            status: "error"
          }
        });
      }
      refreshModelInventory(true);
      finishStream();
    });
    es.onerror = () => {
      if (closed) return;
      fallback.transportErrored = true;
      dispatch({
        type: "UPD_MSG",
        id: asstMsgId,
        patch: {
          status: "streaming",
          statusText: "Run stream interrupted. Checking backend status..."
        }
      });
      refreshRunSnapshot();
    };
  }, [apiBase, appDispatch, refreshModelInventory, chat.messages, clearActiveRunState]);
  reactExports.useEffect(() => {
    const activeRunId2 = String(appState.activeRunId || "").trim();
    if (!activeRunId2) return;
    if (resumeAttemptedRunRef.current === activeRunId2) return;
    resumeAttemptedRunRef.current = activeRunId2;
    let cancelled = false;
    (async () => {
      try {
        const existing = (chat.messages || []).find((m2) => String(m2.runId || "") === activeRunId2);
        const resp = await fetch(`${apiBase}/api/runs/${encodeURIComponent(activeRunId2)}`);
        const data = await resp.json().catch(() => ({}));
        if (cancelled) return;
        if (!resp.ok) {
          if (existing?.id) {
            dispatch({
              type: "UPD_MSG",
              id: existing.id,
              patch: buildFailedMessagePatch(data, activeRunId2, "failed", existing)
            });
          }
          dispatch({ type: "CLEAR_AWAITING" });
          clearActiveRunState();
          return;
        }
        const status = runSnapshotStatus(data);
        if (TERMINAL_RUN_STATUSES.has(status)) {
          if (existing?.id) {
            dispatch({
              type: "UPD_MSG",
              id: existing.id,
              patch: status === "completed" ? buildCompletedMessagePatch(data, existing) : buildFailedMessagePatch(data, activeRunId2, status, existing)
            });
          }
          dispatch({ type: "CLEAR_AWAITING" });
          clearActiveRunState();
          return;
        }
        let asstMsgId = "";
        if (status === "awaiting_user_input" && !buildAwaitingState(data, existing || {})) {
          if (existing?.id) {
            dispatch({
              type: "UPD_MSG",
              id: existing.id,
              patch: buildInvalidAwaitingErrorPatch(data, activeRunId2, existing)
            });
          }
          dispatch({ type: "CLEAR_AWAITING" });
          clearActiveRunState();
          return;
        }
        if (existing?.id) {
          const awaitingPatch = status === "awaiting_user_input" ? buildAwaitingState(data, existing) : null;
          asstMsgId = existing.id;
          dispatch({
            type: "UPD_MSG",
            id: asstMsgId,
            patch: {
              ...status === "awaiting_user_input" ? {
                ...runSnapshotMessageMeta(data),
                ...awaitingPatch,
                status: "awaiting"
              } : buildRunningMessagePatch(data, existing)
            }
          });
          if (status === "awaiting_user_input" && awaitingPatch) {
            dispatch({
              type: "SET_AWAITING",
              ctx: buildAwaitingContext(data, activeRunId2, asstMsgId, awaitingPatch)
            });
          }
          if (status !== "awaiting_user_input") dispatch({ type: "CLEAR_AWAITING" });
        } else {
          const awaitingPatch = status === "awaiting_user_input" ? buildAwaitingState(data) : null;
          asstMsgId = `a-${activeRunId2}-resume`;
          dispatch({
            type: "ADD_MSG",
            msg: {
              id: asstMsgId,
              role: "assistant",
              content: "",
              steps: [],
              progress: [],
              logs: [],
              status: status === "awaiting_user_input" ? "awaiting" : "streaming",
              runId: activeRunId2,
              runStartedAt: data?.started_at || (/* @__PURE__ */ new Date()).toISOString(),
              runOutputDir: String(data?.run_output_dir || data?.output_dir || data?.resume_output_dir || "").trim(),
              executionLogPath: resolveRunSnapshotLogPath(data),
              lastKnownRunStatus: runSnapshotStatus(data),
              lastError: runSnapshotErrorText(data, activeRunId2, status),
              mode: chat.mode,
              modeLabel: modeLabel(chat.mode),
              approvalScope: awaitingPatch?.approvalScope || "",
              approvalKind: awaitingPatch?.approvalKind || "",
              approvalRequest: awaitingPatch?.approvalRequest || null,
              awaitingDecision: awaitingPatch?.awaitingDecision || "reply",
              approvalState: awaitingPatch?.approvalState || "",
              ts: /* @__PURE__ */ new Date(),
              ...status === "awaiting_user_input" ? awaitingPatch : {}
            }
          });
          if (status === "awaiting_user_input" && awaitingPatch) {
            dispatch({
              type: "SET_AWAITING",
              ctx: buildAwaitingContext(data, activeRunId2, asstMsgId, awaitingPatch)
            });
          }
        }
        dispatch({ type: "SET_RUN", id: activeRunId2 });
        if (status !== "awaiting_user_input") dispatch({ type: "CLEAR_AWAITING" });
        dispatch({ type: "SET_STREAMING", val: status !== "awaiting_user_input" });
        appDispatch({ type: "SET_STREAMING", streaming: status !== "awaiting_user_input" });
        openStream(activeRunId2, asstMsgId);
      } catch (_2) {
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appState.activeRunId, apiBase, openStream, chat.messages, chat.mode, appDispatch, clearActiveRunState]);
  const stopRun = reactExports.useCallback(async () => {
    const runId = String(stopTargetRunId || "").trim();
    if (!runId) return;
    esRef.current?.close();
    const activeMsg = [...chat.messages || []].reverse().find((msg) => String(msg?.runId || "").trim() === runId && isPendingRunStatus(msg?.status));
    if (activeMsg) {
      dispatch({ type: "UPD_MSG", id: activeMsg.id, patch: { status: "done" } });
    }
    dispatch({ type: "CLEAR_AWAITING" });
    if (runId) {
      await fetch(`${apiBase}/api/runs/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId })
      }).catch(() => {
      });
    }
    clearActiveRunState();
  }, [stopTargetRunId, chat.messages, apiBase, clearActiveRunState]);
  const submitSkillApproval = reactExports.useCallback(async (scope, note = "") => {
    const ctx = chat.awaitingContext || {};
    const request = ctx.approvalRequest && typeof ctx.approvalRequest === "object" ? ctx.approvalRequest : {};
    const metadata = request.metadata && typeof request.metadata === "object" ? request.metadata : {};
    const skillId = String(metadata.skill_id || "").trim();
    const sessionId = String(metadata.session_id || "").trim();
    if (!skillId) throw new Error("Missing skill id for approval.");
    const response = await fetch(`${apiBase}/api/marketplace/skills/${encodeURIComponent(skillId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scope,
        note: String(note || "").trim() || `Approved ${String(metadata.skill_slug || skillId)} from the desktop chat UI (${scope}).`,
        session_id: sessionId
      })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      throw new Error(data.error || data.detail || response.statusText);
    }
    const reply = scope === "always" ? "approve always" : scope === "session" ? "approve for this session" : "approve once";
    await send(reply, true);
  }, [apiBase, chat.awaitingContext, send]);
  const handleKey = (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      send();
    }
  };
  const isOnline = appState.backendStatus === "running";
  const studioModelLabel = (() => {
    if (chat.mode === "research" && effectiveDeepResearchModel?.model) {
      return `Research · ${effectiveDeepResearchModel.shortLabel || composerModelMeta.label}`;
    }
    if (selectedModelMeta.model) return `Selected · ${selectedModelMeta.label}`;
    const provider = String(modelInventory?.configured_provider || "").trim();
    const model = String(modelInventory?.configured_model || "").trim();
    if (provider && model) return `Auto · ${resolveSelectedModel(`${provider}/${model}`).label}`;
    return "Auto · Backend default";
  })();
  const attachFiles = reactExports.useCallback(async () => {
    const paths = await window.kendrAPI?.dialog.openFiles([{ name: "All Files", extensions: ["*"] }]);
    if (!Array.isArray(paths) || !paths.length) return;
    setAttachments((prev) => {
      const seen2 = new Set(prev.map((item) => item.path));
      const next = [...prev];
      for (const filePath of paths) {
        if (seen2.has(filePath)) continue;
        next.push({ path: filePath, type: detectAttachmentType(filePath), name: basename$1(filePath) });
        seen2.add(filePath);
      }
      return next;
    });
  }, []);
  const attachFolder = reactExports.useCallback(async () => {
    const dir = await window.kendrAPI?.dialog.openDirectory();
    if (!dir) return;
    setAttachments((prev) => prev.some((item) => item.path === dir) ? prev : [...prev, { path: dir, type: "folder", name: basename$1(dir) }]);
  }, []);
  const removeAttachment = reactExports.useCallback((path) => {
    setAttachments((prev) => prev.filter((item) => item.path !== path));
  }, []);
  const handlePaste = reactExports.useCallback(async (e) => {
    const items = Array.from(e.clipboardData?.items || []);
    const imageItems = items.filter((item) => item.kind === "file" && String(item.type || "").startsWith("image/"));
    if (!imageItems.length) return;
    e.preventDefault();
    const api2 = window.kendrAPI;
    const saved = [];
    for (const item of imageItems) {
      const file = item.getAsFile();
      if (!file) continue;
      try {
        const dataUrl = await readBlobAsDataUrl(file);
        const result = await api2?.clipboard?.saveImage({
          dataUrl,
          name: file.name ? file.name.replace(/\.[^.]+$/, "") : "pasted-screenshot"
        });
        if (result?.path) {
          saved.push({
            path: result.path,
            type: "image",
            name: basename$1(result.path)
          });
        }
      } catch (_2) {
      }
    }
    if (!saved.length) return;
    setAttachments((prev) => {
      const seen2 = new Set(prev.map((item) => item.path));
      const next = [...prev];
      for (const item of saved) {
        if (seen2.has(item.path)) continue;
        next.push(item);
        seen2.add(item.path);
      }
      return next;
    });
  }, []);
  const MODES = [
    { id: "chat", label: "💬 Chat" },
    { id: "plan", label: "🗺 Plan" },
    { id: "agent", label: "✨ Agent" },
    { id: "research", label: "🔬 Deep Research" }
  ];
  const showLandingLayout = minimalStudio && !hasMessages;
  const composerBanner = composerRunActive ? "Run active. Live execution log updates are streaming in the current run bubble. Stop the run before sending another message." : displayableAwaitingContext ? "Run paused for your input. Reply here to continue the same workflow." : "";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-panel${fullWidth ? " kc-panel--full" : ""}${showLandingLayout ? " kc-panel--landing" : ""}${chat.mode === "research" ? " kc-panel--research-active" : ""}`, children: [
    !hideHeader && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-header", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-logo", children: [
        "K",
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "endr" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-header-model", title: studioModelLabel, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `kc-header-model-dot ${composerModelMeta.isLocal || String(modelInventory?.configured_provider || "").toLowerCase() === "ollama" ? "local" : ""}` }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: studioModelLabel }),
        !studioMode && appState.projectRoot && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-header-model-project", children: basename$1(appState.projectRoot) })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-header-status", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `kc-dot ${isOnline ? "kc-dot--on" : ""}` }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-header-status-text", children: isOnline ? "connected" : appState.backendStatus })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-header-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-icon-btn", title: "Chat history", onClick: () => setShowHistory((v2) => !v2), children: /* @__PURE__ */ jsxRuntimeExports.jsx(HistoryIcon, {}) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-icon-btn", title: "New chat", onClick: newChat, children: /* @__PURE__ */ jsxRuntimeExports.jsx(ClearIcon, {}) }),
        !fullWidth && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-icon-btn", title: "Close", onClick: () => appDispatch({ type: "TOGGLE_CHAT" }), children: "✕" })
      ] })
    ] }),
    !minimalStudio && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-mode-bar", children: MODES.map((m2) => {
      const requiresAgent = m2.id === "agent" || m2.id === "plan";
      const disabled = requiresAgent && !selectedModelAgentCapable;
      return /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: `kc-mode-pill ${chat.mode === m2.id ? "kc-mode-pill--active" : ""} ${disabled ? "kc-mode-pill--disabled" : ""}`,
          onClick: () => {
            if (disabled) return;
            dispatch({ type: "SET_MODE", mode: m2.id });
          },
          title: disabled ? "Selected model cannot run planning or agent workflows." : "",
          children: m2.label
        },
        m2.id
      );
    }) }),
    minimalStudio && hasMessages && studioAccessory && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-compact-toolbar", children: studioAccessory }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-conversation-shell${chat.mode === "research" ? " kc-conversation-shell--research" : ""}`, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-messages", children: [
        chat.messages.length === 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
          minimalStudio && studioAccessory && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-landing-accessory", children: studioAccessory }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(WelcomeScreen, { minimal: minimalStudio, onSuggest: (s) => {
            setInput(s);
            inputRef.current?.focus();
          } })
        ] }),
        chat.messages.map(
          (msg) => msg.role === "user" ? /* @__PURE__ */ jsxRuntimeExports.jsx(UserMessage, { msg }, msg.id) : /* @__PURE__ */ jsxRuntimeExports.jsx(AssistantMessage, { msg, onQuickReply: (reply) => send(reply, true), onSendSuggestion: (reply) => send(reply, true), onOpenArtifact: openArtifact, onDownloadArtifact: downloadArtifact, onReviewArtifact: reviewArtifact }, msg.id)
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: messagesEndRef })
      ] }),
      chat.mode === "research" && /* @__PURE__ */ jsxRuntimeExports.jsx(
        DeepResearchPanel,
        {
          dr,
          updateDr,
          collapsed: dr.collapsed,
          modelOptions: deepResearchModelState.options,
          inheritedModel: deepResearchModelState.inheritedOption,
          inheritedReason: deepResearchModelState.inheritedReason,
          effectiveModel: deepResearchModelState.effectiveOption,
          effectiveModelSource: deepResearchModelState.effectiveSource,
          recommendedDeepResearchModel,
          recommendedDeepResearchEvidenceStage,
          searchProviderState: deepResearchSearchProviderState,
          effectiveSearchProvider: effectiveDeepResearchSearchProvider,
          indexedKbs: indexedResearchKbs,
          activeKb: activeResearchKb,
          selectedKb: selectedResearchKb,
          projectRoot: appState.projectRoot,
          apiBase,
          refreshKbs: loadResearchKbs,
          activeDeepResearchWorkflowCombo,
          workflowStageOptions: deepResearchWorkflowStageOptions
        }
      )
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      GitDiffPreview,
      {
        cwd: appState.projectRoot,
        filePath: diffPreviewPath,
        onClose: () => setDiffPreviewPath(""),
        onOpenFile: (filePath) => openArtifact({ path: filePath })
      }
    ),
    displayableAwaitingContext && !inlineAwaiting && /* @__PURE__ */ jsxRuntimeExports.jsx(
      AgentApprovalModal,
      {
        ctx: chat.awaitingContext,
        value: resumeInput,
        onChange: setResumeInput,
        onSend: () => send(resumeInput, true),
        onQuickReply: (r2) => send(r2, true),
        onSkillApprove: submitSkillApproval,
        onStop: stopRun,
        onDismiss: () => {
          dispatch({ type: "CLEAR_AWAITING" });
          setResumeInput("");
        }
      }
    ),
    showHistory && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-history-overlay", onClick: (e) => e.target === e.currentTarget && setShowHistory(false), children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-history-drawer", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-history-hdr", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Chat History" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-icon-btn", onClick: () => setShowHistory(false), children: "✕" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-history-new-btn", onClick: newChat, children: "+ New Chat" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-history-list", children: /* @__PURE__ */ jsxRuntimeExports.jsx(HistoryList, { sessions, onLoad: loadSession, onDelete: deleteSession }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-history-footer", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(ClockIcon, { size: 12 }),
        (appState.settings?.chatHistoryRetentionDays ?? 14) > 0 ? `Auto-deleted after ${appState.settings?.chatHistoryRetentionDays ?? 14} days · configure in Settings` : "History kept forever · configure in Settings"
      ] })
    ] }) }),
    stickyChecklist.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx(
      StickyChecklist,
      {
        checklist: stickyChecklist,
        title: stickyChecklistMsg?.status === "awaiting" ? "Checklist waiting" : "Checklist"
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-input-area", children: [
      !!composerBanner && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: `kc-composer-state${composerRunActive ? " kc-composer-state--running" : " kc-composer-state--awaiting"}`, children: composerBanner }),
      (showInlineAttachmentTools || attachments.length > 0) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-attach-bar", children: [
        showInlineAttachmentTools && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-attach-actions", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-attach-btn", onClick: attachFiles, disabled: composerRunActive, children: "+ Files" }),
          studioMode && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-attach-btn", onClick: attachFolder, disabled: composerRunActive, children: "+ Folder" }),
          chat.mode === "agent" || chat.mode === "plan" ? /* @__PURE__ */ jsxRuntimeExports.jsxs(
            "span",
            {
              className: `kc-mcp-indicator${mcpEnabled && mcpUndiscovered > 0 ? " kc-mcp-indicator--warn" : ""}`,
              title: mcpUndiscovered > 0 ? `${mcpUndiscovered} server${mcpUndiscovered !== 1 ? "s have" : " has"} no tools discovered yet — open MCP Settings to run discovery` : `${mcpServerCount} MCP server${mcpServerCount !== 1 ? "s" : ""} active`,
              children: [
                "🔌 MCP ",
                mcpServerCount > 0 ? `· ${mcpServerCount}` : "",
                mcpUndiscovered > 0 ? " ⚠" : ""
              ]
            }
          ) : /* @__PURE__ */ jsxRuntimeExports.jsxs(
            "button",
            {
              className: `kc-attach-btn kc-mcp-toggle${mcpEnabled ? " kc-mcp-toggle--on" : ""}${mcpEnabled && mcpUndiscovered > 0 ? " kc-mcp-toggle--warn" : ""}`,
              onClick: () => setMcpEnabled((v2) => !v2),
              disabled: composerRunActive,
              title: mcpEnabled && mcpUndiscovered > 0 ? `${mcpUndiscovered} server${mcpUndiscovered !== 1 ? "s have" : " has"} no tools discovered — open MCP Settings to run discovery` : mcpEnabled ? "Disable MCP tools for this chat" : `Enable MCP tools (${mcpServerCount} server${mcpServerCount !== 1 ? "s" : ""} available)`,
              children: [
                "🔌 MCP ",
                mcpEnabled ? "ON" : "OFF",
                mcpEnabled && mcpUndiscovered > 0 ? " ⚠" : ""
              ]
            }
          )
        ] }),
        !!attachments.length && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-attach-list", children: attachments.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-attach-chip", title: item.path, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
            item.type === "folder" ? "📁" : item.type === "image" ? "🖼" : "📄",
            " ",
            item.name
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: () => removeAttachment(item.path), children: "×" })
        ] }, item.path)) })
      ] }),
      !studioMode && appState.projectRoot && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-project-badge", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
        "📁 ",
        appState.projectRoot.split(/[\\/]/).pop()
      ] }) }),
      showInlineContextTools && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-context-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-context-badge", title: `Estimated context usage: ${estimatedContextTokens} / ${contextLimit} tokens (${contextPct}%)`, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-context-icon", children: "🧠" }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-context-text", children: [
            estimatedContextTokens.toLocaleString(),
            " / ",
            contextLimit.toLocaleString(),
            " ctx"
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-context-bar", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            "div",
            {
              className: `kc-context-fill${contextPct >= 90 ? " full" : contextPct >= 75 ? " warn" : ""}`,
              style: { width: `${contextPct}%` }
            }
          ) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-attach-btn", onClick: compactContext, title: "Compact context and continue in a fresh backend session", disabled: composerRunActive, children: "Compact" })
      ] }),
      (showPlanSuggestion || showActiveWorkflowChip) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-smart-tools", children: [
        showPlanSuggestion && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-smart-chip kc-smart-chip--suggest", onClick: () => dispatch({ type: "SET_MODE", mode: "plan" }), children: "Create a plan" }),
        showActiveWorkflowChip && /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "kc-smart-chip kc-smart-chip--active",
            onClick: () => dispatch({ type: "SET_MODE", mode: "chat" }),
            children: chat.mode === "plan" ? "Plan mode on" : chat.mode === "agent" ? "Agent mode on" : "Deep research on"
          }
        )
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-input-row", children: [
        minimalStudio && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-composer-menu", ref: composerMenuRef, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-composer-plus", onClick: () => setComposerMenuOpen((value) => !value), title: "Add files or tools", disabled: composerRunActive, children: "+" }),
          composerMenuOpen && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-composer-pop", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-composer-pop-item", onClick: () => {
              setComposerMenuOpen(false);
              attachFiles();
            }, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-composer-pop-main", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(PaperclipIcon, {}),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Add files" })
            ] }) }),
            studioMode && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-composer-pop-item", onClick: () => {
              setComposerMenuOpen(false);
              attachFolder();
            }, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-composer-pop-main", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(FolderIcon, {}),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Add folder" })
            ] }) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-composer-pop-sep" }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs(
              "button",
              {
                className: `kc-composer-pop-item ${chat.mode === "plan" ? "active" : ""}${!selectedModelAgentCapable ? " kc-composer-pop-item--disabled" : ""}`,
                onClick: () => {
                  if (!selectedModelAgentCapable) return;
                  dispatch({ type: "SET_MODE", mode: chat.mode === "plan" ? "chat" : "plan" });
                  setComposerMenuOpen(false);
                },
                title: !selectedModelAgentCapable ? "Selected model cannot run planning workflows." : "",
                children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-composer-pop-main", children: [
                    /* @__PURE__ */ jsxRuntimeExports.jsx(PlanModeIcon, {}),
                    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Plan mode" })
                  ] }),
                  chat.mode === "plan" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-composer-pop-badge", children: "On" })
                ]
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsxs(
              "button",
              {
                className: `kc-composer-pop-item ${chat.mode === "agent" ? "active" : ""}${!selectedModelAgentCapable ? " kc-composer-pop-item--disabled" : ""}`,
                onClick: () => {
                  if (!selectedModelAgentCapable) return;
                  dispatch({ type: "SET_MODE", mode: chat.mode === "agent" ? "chat" : "agent" });
                  setComposerMenuOpen(false);
                },
                title: !selectedModelAgentCapable ? "Selected model cannot run agent workflows." : "",
                children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-composer-pop-main", children: [
                    /* @__PURE__ */ jsxRuntimeExports.jsx(AgentModeIcon, {}),
                    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Agent mode" })
                  ] }),
                  chat.mode === "agent" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-composer-pop-badge", children: "On" })
                ]
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsxs(
              "button",
              {
                className: `kc-composer-pop-item ${chat.mode === "research" ? "active" : ""}`,
                onClick: () => {
                  dispatch({ type: "SET_MODE", mode: chat.mode === "research" ? "chat" : "research" });
                  setComposerMenuOpen(false);
                },
                children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-composer-pop-main", children: [
                    /* @__PURE__ */ jsxRuntimeExports.jsx(ResearchModeIcon, {}),
                    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Deep research" })
                  ] }),
                  chat.mode === "research" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-composer-pop-badge", children: "On" })
                ]
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-composer-pop-sep" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "button",
              {
                className: `kc-composer-pop-item ${mcpEnabled ? "active" : ""}`,
                onClick: () => {
                  setMcpEnabled((value) => !value);
                  setComposerMenuOpen(false);
                },
                children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-composer-pop-main", children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx(PlugModeIcon, {}),
                  /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
                    "MCP ",
                    mcpEnabled ? "on" : "off"
                  ] })
                ] })
              }
            )
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "textarea",
          {
            ref: inputRef,
            className: "kc-input",
            placeholder: minimalStudio ? chat.mode === "plan" ? "Ask for a plan first. Kendr will outline the steps before doing the work…" : "Search, ask, or tell Kendr what to do…" : chat.mode === "research" ? "Describe the deep research task, scope, and output you want…" : chat.mode === "plan" ? "Ask for a plan first. Kendr will outline steps and wait before implementation… (Ctrl+Enter)" : chat.mode === "security" ? "Describe the target and scope…" : chat.mode === "agent" ? "Ask the agent to investigate, reason step by step, and do the detailed work… (Ctrl+Enter)" : "Ask a direct question… (Ctrl+Enter)",
            value: input,
            onChange: (e) => setInput(e.target.value),
            onPaste: handlePaste,
            onKeyDown: handleKey,
            rows: minimalStudio ? 1 : 3,
            disabled: composerRunActive
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: `kc-send-btn ${composerRunActive ? "kc-send-btn--stop" : ""}`,
            onClick: composerRunActive ? () => stopRun() : () => send(),
            disabled: !composerRunActive && !input.trim(),
            title: composerRunActive ? "Stop active run" : "Send (Ctrl+Enter)",
            children: composerRunActive ? "Stop" : /* @__PURE__ */ jsxRuntimeExports.jsx(SendIcon$1, {})
          }
        )
      ] }),
      showInlineFlowStrip && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-flow-strip", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `kc-flow-chip kc-flow-chip--${chat.mode}`, children: chat.mode === "plan" ? "Plan first" : chat.mode === "agent" ? "Agent run" : chat.mode === "research" ? "Research flow" : "Quick answer" }),
        !studioMode && appState.projectRoot && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-flow-chip", children: [
          "Workspace · ",
          basename$1(appState.projectRoot)
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-flow-chip", children: composerModelMeta.model ? composerModelMeta.label : "Backend auto" }),
        chat.mode === "plan" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-flow-chip kc-flow-chip--muted", children: "waits before implement" })
      ] })
    ] })
  ] });
}
function DeepResearchPanel({
  dr,
  updateDr,
  collapsed = false,
  modelOptions = [],
  inheritedModel = null,
  inheritedReason = "",
  effectiveModel = null,
  effectiveModelSource = "none",
  recommendedDeepResearchModel = null,
  recommendedDeepResearchEvidenceStage = null,
  searchProviderState = { options: [] },
  effectiveSearchProvider = null,
  indexedKbs = [],
  activeKb = null,
  selectedKb = null,
  projectRoot = "",
  apiBase = "",
  refreshKbs = null,
  activeDeepResearchWorkflowCombo = null,
  workflowStageOptions = []
}) {
  const api = window.kendrAPI;
  const [kbSetupState, setKbSetupState] = reactExports.useState({ status: "idle", message: "" });
  const depthPreset = resolveDeepResearchDepthPreset(dr.depthMode, dr.pages);
  const recommendedStageSelections = reactExports.useMemo(() => {
    const next = {};
    const stages = Array.isArray(activeDeepResearchWorkflowCombo?.stages) ? activeDeepResearchWorkflowCombo.stages : [];
    for (const stage of stages) {
      const stageName = String(stage?.stage || "").trim();
      const provider = String(stage?.provider || "").trim();
      const model = String(stage?.model || "").trim();
      if (stageName && provider && model) next[stageName] = `${provider}/${model}`;
    }
    return next;
  }, [activeDeepResearchWorkflowCombo]);
  const actionableWorkflowStageOptions = reactExports.useMemo(() => (Array.isArray(workflowStageOptions) ? workflowStageOptions : []).filter((stageOption) => ["router", "merge", "verify"].includes(String(stageOption?.stage || "").trim())), [workflowStageOptions]);
  const stageOverrideSelections = dr.multiModelStageOverrides && typeof dr.multiModelStageOverrides === "object" ? dr.multiModelStageOverrides : {};
  const updateStageOverride = (stageName, value) => {
    const normalizedStage = String(stageName || "").trim();
    if (!normalizedStage) return;
    const normalizedValue = String(value || "").trim();
    const recommendedValue = String(recommendedStageSelections[normalizedStage] || "").trim();
    const nextOverrides = { ...stageOverrideSelections };
    if (!normalizedValue || normalizedValue === recommendedValue) delete nextOverrides[normalizedStage];
    else nextOverrides[normalizedStage] = normalizedValue;
    updateDr({ multiModelStageOverrides: nextOverrides });
  };
  const clearStageOverrides = () => updateDr({ multiModelStageOverrides: {} });
  const toggleFormat = (fmt) => {
    const cur = dr.outputFormats;
    const next = cur.includes(fmt) ? cur.filter((f2) => f2 !== fmt) : [...cur, fmt];
    updateDr({ outputFormats: next });
  };
  const toggleSource = (src) => {
    const cur = dr.sources;
    const next = cur.includes(src) ? cur.filter((s) => s !== src) : [...cur, src];
    updateDr({ sources: next });
  };
  const addLocalPath = async () => {
    const dir = await api?.dialog.openDirectory();
    if (dir && !dr.localPaths.includes(dir)) {
      updateDr({ localPaths: [...dr.localPaths, dir] });
    }
  };
  const removeLocalPath = (p2) => updateDr({ localPaths: dr.localPaths.filter((x2) => x2 !== p2) });
  const defaultKbName = (() => {
    const seed = dr.localPaths[0] || projectRoot || "Research";
    const base = basename$1(seed).replace(/\.[^.]+$/, "").trim() || "Research";
    return `${base} KB`;
  })();
  const openSuperRag = (params = {}) => {
    const target = new URL("/rag", apiBase || window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
      if (value == null || value === "") return;
      target.searchParams.set(key, String(value));
    });
    window.open(target.toString(), "_blank", "noopener,noreferrer");
  };
  const watchKbIndex = reactExports.useCallback(async (kbId, kbName) => {
    const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    for (let attempt = 0; attempt < 48; attempt += 1) {
      await pause(2500);
      try {
        const statusResp = await fetch(`${apiBase}/api/rag/kbs/${encodeURIComponent(kbId)}/index/status`);
        const statusData = await statusResp.json().catch(() => ({}));
        const latest = typeof refreshKbs === "function" ? await refreshKbs() : [];
        const latestKb = Array.isArray(latest) ? latest.find((kb2) => kb2.id === kbId) : null;
        const kbStatus = String(latestKb?.status || "").trim().toLowerCase();
        if (statusData?.status === "running" || kbStatus === "indexing") {
          setKbSetupState({
            status: "indexing",
            message: `Active KB "${kbName}" is indexing${statusData?.chunks_indexed ? ` (${statusData.chunks_indexed} chunks so far)` : ""}.`
          });
          continue;
        }
        if (statusData?.status === "done" || statusData?.status === "done_with_errors" || kbStatus === "indexed") {
          setKbSetupState({
            status: kbStatus === "indexed" ? "ready" : "warning",
            message: kbStatus === "indexed" ? `Active KB "${kbName}" is ready for Deep Research.` : `KB "${kbName}" finished indexing with warnings. Check Super-RAG if results look incomplete.`
          });
          return;
        }
        if (statusData?.status === "error") {
          setKbSetupState({
            status: "error",
            message: `KB "${kbName}" failed to index. Open Super-RAG to inspect the source setup.`
          });
          return;
        }
      } catch (_2) {
      }
    }
    setKbSetupState({
      status: "indexing",
      message: `KB setup started for "${kbName}". Indexing is still running; you can monitor it in Super-RAG.`
    });
  }, [apiBase, refreshKbs]);
  const quickCreateActiveKb = reactExports.useCallback(async () => {
    const promptName = window.prompt("Name for the new active knowledge base:", defaultKbName);
    const kbName = String(promptName || "").trim();
    if (!kbName) return;
    setKbSetupState({ status: "working", message: `Creating "${kbName}"…` });
    try {
      const createResp = await fetch(`${apiBase}/api/rag/kbs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: kbName,
          description: "Created from Deep Research quick setup."
        })
      });
      const createdKb = await createResp.json().catch(() => ({}));
      if (!createResp.ok || createdKb?.error || !createdKb?.id) {
        throw new Error(createdKb?.error || "Failed to create knowledge base.");
      }
      for (const path of dr.localPaths || []) {
        const sourceResp = await fetch(`${apiBase}/api/rag/kbs/${encodeURIComponent(createdKb.id)}/sources`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: "folder",
            path,
            label: basename$1(path) || path,
            recursive: true,
            max_files: 300
          })
        });
        const sourceData = await sourceResp.json().catch(() => ({}));
        if (!sourceResp.ok || sourceData?.error) {
          throw new Error(sourceData?.error || `Failed to add source: ${path}`);
        }
      }
      const activateResp = await fetch(`${apiBase}/api/rag/kbs/${encodeURIComponent(createdKb.id)}/activate`, { method: "POST" });
      const activateData = await activateResp.json().catch(() => ({}));
      if (!activateResp.ok || activateData?.error) {
        throw new Error(activateData?.error || "Failed to activate knowledge base.");
      }
      updateDr({ kbEnabled: true, kbId: "" });
      if (typeof refreshKbs === "function") await refreshKbs();
      if ((dr.localPaths || []).length) {
        const indexResp = await fetch(`${apiBase}/api/rag/kbs/${encodeURIComponent(createdKb.id)}/index`, { method: "POST" });
        if (!indexResp.ok) {
          throw new Error("Knowledge base created, but indexing could not be started.");
        }
        setKbSetupState({
          status: "indexing",
          message: `Active KB "${kbName}" created from ${dr.localPaths.length} folder${dr.localPaths.length === 1 ? "" : "s"}. Indexing started.`
        });
        watchKbIndex(createdKb.id, kbName);
      } else {
        setKbSetupState({
          status: "warning",
          message: `Active KB "${kbName}" was created, but it has no sources yet. Add a folder in Super-RAG to finish setup.`
        });
        openSuperRag({ kb: createdKb.id });
      }
    } catch (err) {
      setKbSetupState({
        status: "error",
        message: String(err?.message || err || "KB setup failed.")
      });
    }
  }, [apiBase, defaultKbName, dr.localPaths, openSuperRag, refreshKbs, updateDr, watchKbIndex]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: `dr-panel${collapsed ? " dr-panel--collapsed" : ""}`, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-panel-inner", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-panel-header", onClick: () => updateDr({ collapsed: !dr.collapsed }), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-panel-title", children: "🔬 Deep Research Settings" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-summary", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-sum-pill", children: depthPreset.summary }),
        effectiveModel?.model && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-sum-pill", children: effectiveModel.model }),
        dr.webSearchEnabled && effectiveSearchProvider?.label && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-sum-pill", children: effectiveSearchProvider.label }),
        dr.multiModelEnabled && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-sum-pill", children: dr.multiModelStrategy === "cheapest" ? "Cheapest combo" : "Best combo" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-sum-pill", children: dr.citationStyle.toUpperCase() }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-sum-pill", children: dr.outputFormats.join("·") }),
        dr.webSearchEnabled && effectiveModel?.model && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-sum-pill", children: hasNativeWebSearchCapability(effectiveModel.provider, effectiveModel.model, effectiveModel.capabilities) ? "Native web" : "Kendr search" }),
        !dr.webSearchEnabled && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-sum-pill dr-sum-warn", children: "Local only" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "dr-collapse-btn", children: dr.collapsed ? "▸" : "▾" })
    ] }),
    !dr.collapsed && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-body", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-grid", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Research Depth" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "select",
            {
              className: "dr-select",
              value: depthPreset.id,
              onChange: (e) => {
                const preset = resolveDeepResearchDepthPreset(e.target.value, 0);
                updateDr({ depthMode: preset.id, pages: preset.pages });
              },
              children: DEEP_RESEARCH_DEPTH_PRESETS.map((preset) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: preset.id, children: preset.label }, preset.id))
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: depthPreset.hint }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "Kendr uses this as an execution-depth hint. The final exports are sized automatically from source density, citations, and structure instead of targeting an exact page count." })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Deep Research Model" }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs(
            "select",
            {
              className: "dr-select",
              value: dr.researchModel || "",
              onChange: (e) => updateDr({ researchModel: e.target.value }),
              children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "", children: inheritedModel?.shortLabel ? `Use selected chat model · ${inheritedModel.shortLabel}` : "Use the chat header model" }),
                modelOptions.map((option) => /* @__PURE__ */ jsxRuntimeExports.jsx(
                  "option",
                  {
                    value: option.value,
                    disabled: !!option.disabledReason,
                    children: option.disabledReason ? `${option.shortLabel} — ${option.disabledReason}` : option.shortLabel
                  },
                  option.value
                ))
              ]
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: effectiveModel ? `Active for Deep Research: ${effectiveModel.shortLabel}${effectiveModelSource === "recommended" ? " (recommended)" : effectiveModelSource === "header" ? " (from header model)" : ""}.` : "No compatible Deep Research model is available with the current settings." }),
          recommendedDeepResearchModel && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: effectiveModel && recommendedDeepResearchModel.value === effectiveModel.value ? `Best-fit suggestion: ${recommendedDeepResearchModel.shortLabel}.` : `Best-fit suggestion: ${recommendedDeepResearchModel.shortLabel}${effectiveModel ? `, while this run is currently using ${effectiveModel.shortLabel}.` : "."}` }),
          dr.webSearchEnabled ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: effectiveModel && hasNativeWebSearchCapability(effectiveModel.provider, effectiveModel.model, effectiveModel.capabilities) ? "This model can use native web search for Deep Research." : "This model will use Kendr web search fallback: Kendr gathers sources, then the selected model synthesizes the report." }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "Local-only runs can use local models or any configured provider with enough context." }),
          dr.multiModelEnabled && recommendedDeepResearchEvidenceStage?.provider && recommendedDeepResearchEvidenceStage?.model && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-note", children: [
            "Multi-model evidence-stage suggestion: ",
            providerDisplayLabel(recommendedDeepResearchEvidenceStage.provider),
            " · ",
            recommendedDeepResearchEvidenceStage.model,
            "."
          ] }),
          !dr.researchModel && inheritedReason && effectiveModel && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-note", children: [
            "The current chat-header model is incompatible here, so this run will fall back to ",
            effectiveModel.shortLabel,
            "."
          ] }),
          dr.multiModelEnabled && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "The selected Deep Research model remains the base fallback. Route, evidence, draft, merge, and verification stages can be overridden by the multi-model workflow plan for this task." })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Citation Style" }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "dr-select", value: dr.citationStyle, onChange: (e) => updateDr({ citationStyle: e.target.value }), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "apa", children: "APA" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "mla", children: "MLA" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "chicago", children: "Chicago" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "ieee", children: "IEEE" })
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Date Range" }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "dr-select", value: dr.dateRange, onChange: (e) => updateDr({ dateRange: e.target.value }), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "all_time", children: "All time" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "1y", children: "Last year" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "2y", children: "Last 2 years" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "5y", children: "Last 5 years" })
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Max Sources" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              className: "dr-input-sm",
              type: "number",
              min: 0,
              step: 10,
              value: dr.maxSources,
              onChange: (e) => updateDr({ maxSources: +e.target.value }),
              placeholder: "0 = auto"
            }
          )
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Search Backend" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "select",
            {
              className: "dr-select",
              value: effectiveSearchProvider?.id || "auto",
              onChange: (e) => updateDr({ searchBackend: e.target.value }),
              disabled: !dr.webSearchEnabled,
              children: searchProviderState.options.map((option) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: option.id, disabled: !option.enabled, children: option.enabled ? option.label : `${option.label} — not configured` }, option.id))
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: !dr.webSearchEnabled ? "Search backend selection is disabled while web search is off." : effectiveSearchProvider?.note || "Choose which backend Kendr should prefer while gathering external sources." }),
          dr.webSearchEnabled && effectiveSearchProvider?.warning && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", style: { color: "var(--warn)" }, children: effectiveSearchProvider.warning })
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-grid", style: { marginTop: 8 }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Output Formats" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-checks", children: ["pdf", "docx", "html", "md"].map((f2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "dr-check", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", checked: dr.outputFormats.includes(f2), onChange: () => toggleFormat(f2) }),
            f2.toUpperCase()
          ] }, f2)) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Source Families" }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-checks", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "dr-check dr-check--web", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(
                "input",
                {
                  type: "checkbox",
                  checked: dr.webSearchEnabled,
                  onChange: (e) => updateDr({ webSearchEnabled: e.target.checked })
                }
              ),
              "🌐 Web Search"
            ] }),
            [["web", "Web"], ["arxiv", "Academic"], ["patents", "Patents"], ["news", "News"], ["reddit", "Community"]].map(([v2, l2]) => /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "dr-check", style: { opacity: dr.webSearchEnabled ? 1 : 0.4 }, children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(
                "input",
                {
                  type: "checkbox",
                  checked: dr.sources.includes(v2),
                  disabled: !dr.webSearchEnabled,
                  onChange: () => toggleSource(v2)
                }
              ),
              l2
            ] }, v2))
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Quality Gates" }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-checks", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "dr-check", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", checked: dr.plagiarismCheck, onChange: (e) => updateDr({ plagiarismCheck: e.target.checked }) }),
              "Plagiarism Check"
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "dr-check", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", checked: dr.checkpointing, onChange: (e) => updateDr({ checkpointing: e.target.checked }) }),
              "Checkpointing"
            ] })
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Model Allocation" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-checks", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "dr-check", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "input",
              {
                type: "checkbox",
                checked: !!dr.multiModelEnabled,
                onChange: (e) => updateDr({ multiModelEnabled: e.target.checked })
              }
            ),
            "Use multi-model workflow"
          ] }) }),
          dr.multiModelEnabled ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs(
              "select",
              {
                className: "dr-select",
                value: dr.multiModelStrategy || "best",
                onChange: (e) => updateDr({ multiModelStrategy: e.target.value === "cheapest" ? "cheapest" : "best" }),
                style: { marginTop: 8 },
                children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "best", children: "Best combination" }),
                  /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "cheapest", children: "Cheapest combination" })
                ]
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "Deep Research can split route, evidence, draft, merge, and verification across different models when the current task enables it." }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: activeDeepResearchWorkflowCombo?.available ? `${dr.multiModelStrategy === "cheapest" ? "Cheapest" : "Best"} combo: ${activeDeepResearchWorkflowCombo.summary || "Stage recommendations are available."}` : "No compatible multi-model Deep Research combination is currently available from the connected providers." }),
            activeDeepResearchWorkflowCombo?.available && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-note", children: [
              "Estimated cost band: ",
              String(activeDeepResearchWorkflowCombo.estimated_cost_band || "unknown"),
              "."
            ] }),
            activeDeepResearchWorkflowCombo?.available && actionableWorkflowStageOptions.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", style: { marginTop: 8 }, children: "The recommendation preset seeds the stage picks below. Change a stage only when you want to pin a different model for that part of the workflow." }),
              actionableWorkflowStageOptions.map((stageOption) => {
                const stageName = String(stageOption.stage || "").trim();
                const selectedValue = String(stageOverrideSelections[stageName] || "").trim();
                const recommendedValue = String(recommendedStageSelections[stageName] || "").trim();
                const recommendedCandidate = (Array.isArray(stageOption.candidates) ? stageOption.candidates : []).find((candidate) => String(candidate?.value || "").trim() === recommendedValue) || null;
                const manualCandidate = (Array.isArray(stageOption.candidates) ? stageOption.candidates : []).find((candidate) => String(candidate?.value || "").trim() === selectedValue) || null;
                return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { marginTop: 10 }, children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "dr-label", children: [
                    stageOption.label,
                    " Model"
                  ] }),
                  /* @__PURE__ */ jsxRuntimeExports.jsxs(
                    "select",
                    {
                      className: "dr-select",
                      value: selectedValue,
                      onChange: (e) => updateStageOverride(stageName, e.target.value),
                      children: [
                        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "", children: recommendedCandidate ? `Use ${dr.multiModelStrategy === "cheapest" ? "cheapest" : "best"} recommendation · ${recommendedCandidate.labelFull || recommendedCandidate.value}` : "Use the recommendation preset" }),
                        (Array.isArray(stageOption.candidates) ? stageOption.candidates : []).map((candidate) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: candidate.value, children: candidate.labelFull || candidate.value }, candidate.value))
                      ]
                    }
                  ),
                  /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: manualCandidate ? `Pinned manually: ${manualCandidate.labelFull || manualCandidate.value}. ${manualCandidate.reason || ""}`.trim() : recommendedCandidate ? `Recommended: ${recommendedCandidate.labelFull || recommendedCandidate.value}. ${recommendedCandidate.reason || ""}`.trim() : "No compatible model candidates are available for this stage." })
                ] }, stageName);
              }),
              Object.keys(stageOverrideSelections).length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx(
                "button",
                {
                  type: "button",
                  className: "dr-action-btn",
                  style: { marginTop: 10 },
                  onClick: clearStageOverrides,
                  children: "Reset Stage Overrides"
                }
              ),
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", style: { marginTop: 8 }, children: "The Deep Research model above controls evidence collection. Section drafting currently follows the merge-stage model during long-document execution." })
            ] })
          ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "Single-model mode keeps the whole task on the selected Deep Research model." })
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", style: { marginTop: 8 }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Local Folders / Files" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-path-row", children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "dr-action-btn", onClick: addLocalPath, children: "+ Browse Folder" }) }),
        dr.localPaths.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-chips", children: dr.localPaths.map((p2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "dr-chip", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
            "📁 ",
            p2.split(/[\\/]/).slice(-2).join("/")
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: () => removeLocalPath(p2), children: "✕" })
        ] }, p2)) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "Folders are read recursively by the backend (local machine paths)." })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", style: { marginTop: 8 }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Explicit Content Links" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "textarea",
          {
            className: "dr-textarea",
            rows: 3,
            placeholder: "https://example.com/report\nhttps://example.com/dataset",
            value: dr.links,
            onChange: (e) => updateDr({ links: e.target.value })
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "These exact URLs will be fetched as part of the report, even if general web search is off." })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-field", style: { marginTop: 8 }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "dr-label", children: "Private Knowledge" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-checks", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "dr-check", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              type: "checkbox",
              checked: !!dr.kbEnabled,
              onChange: (e) => updateDr({ kbEnabled: e.target.checked })
            }
          ),
          "Use knowledge base"
        ] }) }),
        dr.kbEnabled && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-path-row", style: { marginTop: 8 }, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs(
              "select",
              {
                className: "dr-select",
                value: dr.kbId || "",
                disabled: !indexedKbs.length && !activeKb,
                onChange: (e) => updateDr({ kbId: e.target.value }),
                children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "", children: activeKb ? `Active KB (${activeKb.name})` : "Active KB" }),
                  indexedKbs.map((kb2) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: kb2.id, children: kb2.name }, kb2.id))
                ]
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "input",
              {
                className: "dr-input-sm",
                type: "number",
                min: 1,
                max: 50,
                step: 1,
                value: dr.kbTopK || 8,
                onChange: (e) => updateDr({ kbTopK: Math.max(1, Number(e.target.value || 8)) })
              }
            )
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "Use private indexed docs with web research, local files, or a KB-only run. Empty selector means use the active KB." }),
          !indexedKbs.length && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "No indexed knowledge bases found yet. Create one here in one step, or open Super-RAG for the full setup." }),
          dr.kbEnabled && !selectedKb && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "No active indexed KB is available yet. Set one active in Super-RAG or pick an indexed KB here." }),
          dr.kbEnabled && (!indexedKbs.length || !selectedKb) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-path-row", style: { marginTop: 8 }, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "button",
              {
                className: "dr-action-btn",
                onClick: quickCreateActiveKb,
                disabled: kbSetupState.status === "working" || kbSetupState.status === "indexing",
                children: dr.localPaths.length ? "Create Active KB From Folders" : "Create Active KB"
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "button",
              {
                className: "dr-action-btn",
                onClick: () => openSuperRag({ quick: 1, name: defaultKbName }),
                children: "Open Quick KB Setup"
              }
            )
          ] }),
          dr.kbEnabled && !dr.localPaths.length && (!indexedKbs.length || !selectedKb) && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: "Tip: add a local folder above, then one click can create, activate, and start indexing the KB for you." }),
          kbSetupState.message && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "dr-note", children: kbSetupState.message }),
          selectedKb && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "dr-note", children: [
            "KB ready: ",
            selectedKb.name,
            " · ",
            selectedKb.stats?.total_chunks || 0,
            " chunks · top ",
            dr.kbTopK || 8,
            " passages"
          ] })
        ] })
      ] })
    ] })
  ] }) });
}
function WelcomeScreen({ onSuggest, minimal = false }) {
  const SUGGESTIONS = minimal ? [
    "Search files on my machine",
    "Research this deeply",
    "Turn this into a plan"
  ] : [
    "Summarize the attached files for me",
    "Explain this topic simply",
    "Make a plan before implementing this task",
    "Investigate this problem step by step",
    "Run a security assessment",
    "Write a detailed technical report",
    "Compare two approaches and recommend one"
  ];
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-welcome", children: [
    minimal && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-welcome-brow", children: "Orchestrate deep work." }),
    !minimal && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-welcome-logo", children: "⚡" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { className: `kc-welcome-title${minimal ? " kc-welcome-title--hero" : ""}`, children: minimal ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Kendr" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-welcome-title-accent", children: "." })
    ] }) : "Kendr Studio" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "kc-welcome-sub", children: minimal ? "Research, route models, and run agents from one workspace." : "Use Chat for quick answers. Use Plan to outline the work first. Use Agent when you want Kendr to do the detailed work." }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-suggestions", children: SUGGESTIONS.map((s) => /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-suggest", onClick: () => onSuggest(s), children: s }, s)) })
  ] });
}
function UserMessage({ msg }) {
  const attachments = Array.isArray(msg.attachments) ? msg.attachments : [];
  const imageAttachments = attachments.filter((item) => item?.type === "image");
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-row kc-row--user", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-bubble kc-bubble--user", children: [
      msg.modeLabel && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-mode-stamp", children: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `kc-mode-stamp-chip kc-mode-stamp-chip--${String(msg.mode || "chat")}`, children: msg.modeLabel }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-bubble-text", children: msg.content }),
      attachments.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-msg-attachments", children: [
        imageAttachments.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-msg-image-grid", children: imageAttachments.map((item) => {
          const src = attachmentPreviewSrc(item);
          return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-msg-image-card", title: item.path, children: [
            src ? /* @__PURE__ */ jsxRuntimeExports.jsx("img", { src, alt: item.name || "attached image", className: "kc-msg-image" }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-msg-image-fallback", children: "🖼" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-msg-image-name", children: item.name })
          ] }, `img-${item.path}`);
        }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-msg-attach-list", children: attachments.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-msg-attach-chip", title: item.path, children: [
          item.type === "folder" ? "📁" : item.type === "image" ? "🖼" : "📄",
          " ",
          item.name
        ] }, item.path)) })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-bubble-ts", children: formatTs(msg.ts) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-avatar kc-avatar--user", children: "👤" })
  ] });
}
function AssistantMessage({ msg, onQuickReply, onSendSuggestion, onOpenArtifact, onDownloadArtifact, onReviewArtifact }) {
  const [copied, setCopied] = reactExports.useState(false);
  const [nowMs, setNowMs] = reactExports.useState(Date.now());
  const [logsExpanded, setLogsExpanded] = reactExports.useState(true);
  const prevLogCountRef = reactExports.useRef(Array.isArray(msg?.logs) ? msg.logs.length : 0);
  const copy = () => {
    navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  reactExports.useEffect(() => {
    if (!msg?.runId) return;
    if (!["thinking", "streaming", "awaiting"].includes(String(msg?.status || ""))) return;
    const timer = setInterval(() => setNowMs(Date.now()), 1e3);
    return () => clearInterval(timer);
  }, [msg?.runId, msg?.status]);
  reactExports.useEffect(() => {
    const nextCount = Array.isArray(msg?.logs) ? msg.logs.length : 0;
    const prevCount = prevLogCountRef.current;
    if (nextCount > 0 && prevCount === 0 && ["thinking", "streaming", "awaiting"].includes(String(msg?.status || ""))) {
      setLogsExpanded(true);
    }
    prevLogCountRef.current = nextCount;
  }, [msg?.logs, msg?.status]);
  const elapsedSeconds = msg?.runId ? Math.max(0, Math.floor((nowMs - new Date(msg.runStartedAt || msg.ts || Date.now()).getTime()) / 1e3)) : 0;
  const progress = Array.isArray(msg.progress) ? msg.progress : [];
  const logs = Array.isArray(msg.logs) ? msg.logs : [];
  const shellCard = shellCardFromProgress(progress);
  const visibleProgress = progress.filter((item) => !isShellProgressItem$2(item));
  const liveProgressItem = buildLiveProgressItem(visibleProgress, msg.statusText, msg.status);
  const checklist = Array.isArray(msg.checklist) ? msg.checklist : [];
  const activityCards = summarizeRunArtifacts(visibleProgress, msg.artifacts);
  const showActivityCards = activityCards.length > 0 && !isPendingRunStatus(msg.status);
  const hasConcreteAwaiting = messageHasConcreteAwaitingPrompt(msg);
  const inlineApprovalVisible = msg.status === "awaiting" && hasConcreteAwaiting && !isSkillApproval(msg.approvalKind, msg.approvalRequest);
  const planCardVisible = checklist.length > 0 && (msg.mode === "plan" || isPlanApprovalScope(msg.approvalScope, msg.approvalKind, msg.approvalRequest));
  const blockerChips = inferExecutionBlockers({ msg, shellCard, progress: visibleProgress, checklist });
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-row kc-row--assistant", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-avatar kc-avatar--kendr", children: "K" }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-bubble kc-bubble--assistant", children: [
      msg.runId && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-run-hero", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-run-eyebrow", children: "Run" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-run-id", children: msg.runId }),
        msg.modeLabel && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: `kc-run-mode kc-run-mode--${String(msg.mode || "chat")}`, children: msg.modeLabel }),
        msg.runId && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-run-elapsed", children: [
          "⏱ ",
          formatDuration$2(elapsedSeconds)
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: `kc-run-badge kc-run-badge--${msg.status || "thinking"}`, children: { thinking: "Thinking", streaming: "Running", awaiting: "Awaiting Input", done: "Done", error: "Error" }[msg.status] || "Thinking" })
      ] }),
      msg.status === "thinking" && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-thinking", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-typing-dot" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-typing-dot" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-typing-dot" }),
        msg.statusText && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-thinking-text", children: msg.statusText })
      ] }),
      shellCard && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-shell-card kc-shell-card--${shellCard.status || "running"}`, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-shell-card-head", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-shell-card-label", children: "Shell" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-shell-card-title", children: shellCard.title })
        ] }),
        shellCard.command && /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "kc-shell-card-code", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("code", { children: [
          "$ ",
          shellCard.command
        ] }) }),
        shellCard.output && /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "kc-shell-card-output", children: /* @__PURE__ */ jsxRuntimeExports.jsx("code", { children: shellCard.output }) }),
        (shellCard.cwd || shellCard.durationLabel || shellCard.exitCode !== null && shellCard.exitCode !== void 0) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-shell-card-meta", children: [
          shellCard.cwd && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: shellCard.cwd }),
          shellCard.durationLabel && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: shellCard.durationLabel }),
          shellCard.exitCode !== null && shellCard.exitCode !== void 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
            "exit ",
            shellCard.exitCode
          ] })
        ] })
      ] }),
      blockerChips.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-blocker-strip", children: blockerChips.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `kc-blocker-chip kc-blocker-chip--${item.tone || "warn"}`, children: item.label }, item.key)) }),
      showActivityCards && /* @__PURE__ */ jsxRuntimeExports.jsx(RunArtifactCards, { cards: activityCards, runId: msg.runId, onOpenItem: onOpenArtifact, onDownloadItem: onDownloadArtifact, onReviewItem: onReviewArtifact }),
      msg.runId && ["thinking", "streaming", "awaiting"].includes(String(msg.status || "")) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-worklog", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-worklog-head", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
            "Working for ",
            formatDuration$2(elapsedSeconds)
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-worklog-pill", children: liveProgressLabel(liveProgressItem) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-worklog-current kc-worklog-current--${liveProgressItem?.status || "running"}`, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-worklog-current-title", children: liveProgressItem?.title || sanitizeStatusMessage(msg.statusText) || "Working..." }),
          liveProgressItem?.detail && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-worklog-current-detail", children: liveProgressItem.detail }),
          (liveProgressItem?.actor || liveProgressItem?.durationLabel || liveProgressItem?.cwd) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-worklog-current-meta", children: [
            liveProgressItem?.actor && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: liveProgressItem.actor }),
            liveProgressItem?.durationLabel && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: liveProgressItem.durationLabel }),
            liveProgressItem?.cwd && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: liveProgressItem.cwd })
          ] })
        ] })
      ] }),
      msg.runId && (logs.length > 0 || ["thinking", "streaming", "awaiting"].includes(String(msg.status || ""))) && /* @__PURE__ */ jsxRuntimeExports.jsx(
        ExecutionLogPanel,
        {
          logs,
          expanded: logsExpanded,
          onToggle: () => setLogsExpanded((value) => !value)
        }
      ),
      msg.steps?.length > 0 && !isPendingRunStatus(msg.status) && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-steps", children: msg.steps.map((step) => /* @__PURE__ */ jsxRuntimeExports.jsx(StepCard, { step }, step.stepId)) }),
      planCardVisible ? /* @__PURE__ */ jsxRuntimeExports.jsx(
        PlanSummaryCard,
        {
          msg,
          checklist,
          onQuickReply,
          onSendSuggestion
        }
      ) : inlineApprovalVisible ? /* @__PURE__ */ jsxRuntimeExports.jsx(
        InlineAwaitingCard,
        {
          msg,
          onQuickReply,
          onSendSuggestion
        }
      ) : checklist.length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx(ChecklistCard, { checklist }) : null,
      msg.content && msg.status !== "error" && !inlineApprovalVisible && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-content", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-content-actions", children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-copy-btn", onClick: copy, children: copied ? "Copied" : "Copy" }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          MarkdownRenderer,
          {
            content: msg.content,
            isStreaming: ["thinking", "streaming"].includes(String(msg.status || ""))
          }
        )
      ] }),
      msg.status === "error" && msg.content && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-error-msg", children: [
        "⚠ ",
        msg.content
      ] }),
      msg.status === "awaiting" && hasConcreteAwaiting && !inlineApprovalVisible && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-awaiting-note", children: "⏳ Waiting for your reply above…" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-bubble-ts", children: formatTs(msg.ts) })
    ] })
  ] });
}
function ExecutionLogPanel({ logs, expanded, onToggle }) {
  const items = Array.isArray(logs) ? logs : [];
  const summary = summarizeLogFeed(items);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-log-panel${expanded ? "" : " kc-log-panel--collapsed"}`, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-log-panel-head", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-log-panel-meta", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-log-panel-label", children: "Live Execution Log" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-log-panel-summary", children: summary })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-log-panel-toggle", onClick: onToggle, children: expanded ? "Collapse" : "Expand" })
    ] }),
    expanded && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-log-panel-body", children: items.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-log-empty", children: "Waiting for execution log output..." }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-log-lines", children: items.slice(-120).map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-log-line", children: [
      item.clock && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-log-clock", children: item.clock }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-log-text", children: item.text })
    ] }, item.id)) }) })
  ] });
}
function RunArtifactCards({ cards, runId, onOpenItem, onDownloadItem, onReviewItem }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-grid", children: cards.map((card) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-activity-card kc-activity-card--${card.kind}`, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-activity-card-head", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-kind", children: card.kind }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-title", children: card.title })
      ] }),
      card.kind === "edit" && Array.isArray(card.items) && card.items.some((item) => item?.path) && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-action", onClick: () => onReviewItem?.(card.items.find((item) => item?.path)), children: "Review" })
    ] }),
    Array.isArray(card.items) && card.items.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: `kc-activity-card-items${card.kind === "artifact" ? " kc-activity-card-items--stack" : ""}`, children: card.items.slice(0, card.kind === "artifact" ? 6 : 3).map((item) => card.kind === "artifact" ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-activity-card-file", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-activity-card-file-label", children: item.label }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-activity-card-file-actions", children: [
        (runId || item?.downloadUrl) && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-mini", onClick: () => onDownloadItem?.(item, runId), children: "Download" }),
        item?.path && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-mini kc-activity-card-mini--ghost", onClick: () => onOpenItem?.(item), children: "Open" })
      ] })
    ] }, `${item.path || item.name || item.label}-${item.label}`) : item?.path ? /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-item kc-activity-card-item--action", onClick: () => onOpenItem?.(item), children: item.label }, `${item.path}-${item.label}`) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-activity-card-item", children: item.label }, item.label)) })
  ] }, `${card.kind}-${card.title}`)) });
}
function PlanSummaryCard({ msg, checklist, onQuickReply, onSendSuggestion }) {
  const [showSuggest, setShowSuggest] = reactExports.useState(false);
  const [draft, setDraft] = reactExports.useState("");
  const approvalRequest = msg.approvalRequest && typeof msg.approvalRequest === "object" ? msg.approvalRequest : {};
  const approvalActions = approvalRequest.actions && typeof approvalRequest.actions === "object" ? approvalRequest.actions : {};
  const rawSummary = String(approvalRequest.summary || msg.content || "").trim();
  const summary = rawSummary.length > 520 ? `${rawSummary.slice(0, 520).trim()}…` : rawSummary;
  const approvalState = String(msg.approvalState || "").trim().toLowerCase();
  const awaiting = msg.status === "awaiting";
  const stateLabel = awaiting ? "Plan Ready" : approvalState === "approved" ? "Plan Approved" : approvalState === "rejected" ? "Plan Rejected" : approvalState === "suggested" ? "Plan Updated" : "Plan";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-head", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-plan-card-label", children: stateLabel }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-meta", children: [
          checklist.length,
          " task",
          checklist.length === 1 ? "" : "s"
        ] })
      ] }),
      approvalState && approvalState !== "pending" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `kc-plan-card-badge kc-plan-card-badge--${approvalState}`, children: approvalState })
    ] }),
    summary && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-plan-card-summary", children: summary }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-plan-card-list", children: checklist.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsx(ChecklistItem, { item, compact: true }, `plan-${item.step}-${item.title}`)) }),
    awaiting && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-plan-card-btn kc-plan-card-btn--approve", onClick: () => onQuickReply?.("approve"), children: approvalActions.accept_label || "Implement" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: `kc-plan-card-btn kc-plan-card-btn--ghost${showSuggest ? " kc-plan-card-btn--active" : ""}`,
            onClick: () => setShowSuggest((value) => !value),
            children: approvalActions.suggest_label || "Change Plan"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-plan-card-btn kc-plan-card-btn--reject", onClick: () => onQuickReply?.("cancel"), children: approvalActions.reject_label || "Reject" })
      ] }),
      showSuggest && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-suggest", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "textarea",
          {
            className: "kc-plan-card-input",
            rows: 3,
            placeholder: "Say what should change in the plan…",
            value: draft,
            onChange: (event) => setDraft(event.target.value)
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "kc-plan-card-btn kc-plan-card-btn--approve",
            onClick: () => {
              if (!draft.trim()) return;
              onSendSuggestion?.(draft);
              setDraft("");
              setShowSuggest(false);
            },
            disabled: !draft.trim(),
            children: "Send"
          }
        )
      ] })
    ] })
  ] });
}
function InlineAwaitingCard({ msg, onQuickReply, onSendSuggestion }) {
  const [showSuggest, setShowSuggest] = reactExports.useState(false);
  const [draft, setDraft] = reactExports.useState("");
  const approvalRequest = msg.approvalRequest && typeof msg.approvalRequest === "object" ? msg.approvalRequest : {};
  const approvalActions = approvalRequest.actions && typeof approvalRequest.actions === "object" ? approvalRequest.actions : {};
  const title = approvalRequest.title || awaitingTitleFromContext(msg.approvalScope, msg.approvalKind, approvalRequest);
  const summary = String(
    approvalRequest.summary || msg.content || ""
  ).trim();
  const sections = Array.isArray(approvalRequest.sections) ? approvalRequest.sections : [];
  const helpText = String(approvalRequest.help_text || "").trim();
  const decisionMode = String(msg.awaitingDecision || (isApprovalLikeAwaiting(msg.approvalScope, msg.approvalKind, approvalRequest) ? "approval" : "reply")).trim().toLowerCase();
  const hasQuickActions = decisionMode === "approval";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-inline-approval", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-inline-approval-head", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-title", children: title }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-status", children: "awaiting" })
    ] }),
    summary && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-summary", children: /* @__PURE__ */ jsxRuntimeExports.jsx(MarkdownRenderer, { content: summary }) }),
    sections.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-sections", children: sections.map((section, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-inline-approval-section", children: [
      section.title && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-section-title", children: section.title }),
      Array.isArray(section.items) && section.items.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("ul", { className: "kc-inline-approval-list", children: section.items.map((item, itemIndex) => /* @__PURE__ */ jsxRuntimeExports.jsx("li", { children: item }, `${index2}-${itemIndex}`)) })
    ] }, `${section.title || "section"}-${index2}`)) }),
    helpText && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-help", children: helpText }),
    hasQuickActions ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-inline-approval-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-plan-card-btn kc-plan-card-btn--approve", onClick: () => onQuickReply?.("approve"), children: approvalActions.accept_label || "Approve" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: `kc-plan-card-btn kc-plan-card-btn--ghost${showSuggest ? " kc-plan-card-btn--active" : ""}`,
            onClick: () => setShowSuggest((value) => !value),
            children: approvalActions.suggest_label || "Reply"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-plan-card-btn kc-plan-card-btn--reject", onClick: () => onQuickReply?.("cancel"), children: approvalActions.reject_label || "Reject" })
      ] }),
      showSuggest && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-suggest", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "textarea",
          {
            className: "kc-plan-card-input",
            rows: 3,
            placeholder: "Type your reply…",
            value: draft,
            onChange: (event) => setDraft(event.target.value)
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "kc-plan-card-btn kc-plan-card-btn--approve",
            onClick: () => {
              if (!draft.trim()) return;
              onSendSuggestion?.(draft);
              setDraft("");
              setShowSuggest(false);
            },
            disabled: !draft.trim(),
            children: "Send"
          }
        )
      ] })
    ] }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-suggest", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "textarea",
        {
          className: "kc-plan-card-input",
          rows: 3,
          placeholder: "Type your reply…",
          value: draft,
          onChange: (event) => setDraft(event.target.value)
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: "kc-plan-card-btn kc-plan-card-btn--approve",
          onClick: () => {
            if (!draft.trim()) return;
            onSendSuggestion?.(draft);
            setDraft("");
          },
          disabled: !draft.trim(),
          children: "Send reply"
        }
      )
    ] })
  ] });
}
function ChecklistCard({ checklist }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-card", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-title", children: "Checklist" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-list", children: checklist.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsx(ChecklistItem, { item }, `${item.step}-${item.title}`)) })
  ] });
}
function StickyChecklist({ checklist, title }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-sticky-checklist", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-sticky-checklist-head", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: title }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
        checklist.filter((item) => item.done).length,
        "/",
        checklist.length
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-list", children: checklist.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsx(ChecklistItem, { item, compact: true }, `sticky-${item.step}-${item.title}`)) })
  ] });
}
function ChecklistItem({ item, compact = false }) {
  const state = normalizeChecklistStatus(item.status);
  const icon = state === "completed" ? "✓" : state === "skipped" ? "↷" : state === "running" ? "…" : state === "awaiting" ? "!" : state === "failed" || state === "blocked" ? "✗" : "·";
  const detail = String(item.detail || item.reason || item.stdout || item.stderr || "").trim();
  const doneLike = state === "completed" || state === "skipped";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-checklist-item kc-checklist-item--${state}${doneLike ? " kc-checklist-item--done" : ""}`, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-mark", children: icon }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-body", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-checklist-step", children: [
          item.step,
          "."
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-checklist-text", children: item.title })
      ] }),
      !compact && item.command && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-command", children: [
        "$ ",
        item.command
      ] }),
      detail && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-detail", children: detail })
    ] })
  ] });
}
function parseMcpAgentMeta(agentName) {
  const raw = String(agentName || "").trim();
  if (!raw.startsWith("mcp_") || !raw.endsWith("_agent")) return null;
  const inner = raw.slice(4, -6);
  const parts = inner.split("_");
  if (!parts.length) return null;
  const server = parts[0] || "";
  const tool = parts.slice(1).join("_") || "";
  return {
    server,
    tool,
    serverLabel: server.replace(/_/g, " "),
    toolLabel: tool.replace(/_/g, " ")
  };
}
function StepCard({ step }) {
  const [open, setOpen] = reactExports.useState(false);
  const cls = step.status === "completed" || step.status === "success" ? "done" : step.status === "failed" || step.status === "error" ? "failed" : step.status === "running" ? "running" : "pending";
  const mcpMeta = parseMcpAgentMeta(step.agent);
  const ICON = { done: "✓", failed: "✗", running: "●", pending: "·" };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-step kc-step--${cls}`, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-step-dot", children: ICON[cls] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-step-inner", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-step-header", onClick: () => (step.reason || step.message) && setOpen((o) => !o), children: [
        mcpMeta ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-step-agent kc-step-agent--mcp", children: "🔌 MCP" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-step-chip", children: mcpMeta.serverLabel }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-step-agent", children: mcpMeta.toolLabel || step.agent })
        ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-step-agent", children: step.agent }),
        step.message && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-step-msg", children: step.message.slice(0, 80) }),
        step.durationLabel && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-step-dur", children: step.durationLabel }),
        (step.reason || step.message) && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-step-toggle", children: open ? "▾" : "▸" })
      ] }),
      mcpMeta && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-step-reason kc-step-reason--inline", children: [
        "Ran MCP tool `",
        mcpMeta.toolLabel,
        "` via `",
        mcpMeta.serverLabel,
        "`."
      ] }),
      open && step.reason && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-step-reason", children: step.reason })
    ] })
  ] });
}
function MarkdownRenderer({ content, isStreaming = false }) {
  if (isStreaming) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-md kc-md--live", children: /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "kc-md-live-text", children: String(content || "") }) });
  }
  const blocks = parseMarkdown(content || "");
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-md", children: blocks.map((b, i) => /* @__PURE__ */ jsxRuntimeExports.jsx(MarkdownBlock, { block: b }, `${b.type}-${i}`)) });
}
function MarkdownBlock({ block }) {
  if (block.type === "code") return /* @__PURE__ */ jsxRuntimeExports.jsx(CodeBlock, { lang: block.lang, code: block.code });
  if (block.type === "heading") {
    const HeadingTag = `h${Math.min(6, Math.max(1, Number(block.level) || 1))}`;
    return /* @__PURE__ */ jsxRuntimeExports.jsx(HeadingTag, { className: `kc-md-heading kc-md-heading--h${block.level}`, children: /* @__PURE__ */ jsxRuntimeExports.jsx(InlineText, { text: block.text }) });
  }
  if (block.type === "ol") {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("ol", { className: "kc-md-list kc-md-list--ol", start: block.start || 1, children: block.items.map((item, idx) => /* @__PURE__ */ jsxRuntimeExports.jsx("li", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(InlineText, { text: item }) }, idx)) });
  }
  if (block.type === "ul") {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("ul", { className: "kc-md-list kc-md-list--ul", children: block.items.map((item, idx) => /* @__PURE__ */ jsxRuntimeExports.jsx("li", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(InlineText, { text: item }) }, idx)) });
  }
  if (block.type === "quote") {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("blockquote", { className: "kc-md-quote", children: block.lines.map((line, idx) => /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(InlineText, { text: line }) }, idx)) });
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "kc-md-paragraph", children: /* @__PURE__ */ jsxRuntimeExports.jsx(InlineText, { text: block.text }) });
}
function parseMarkdown(content) {
  const lines = String(content || "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  const isBlockStart = (line) => /^```/.test(line) || /^(#{1,6})\s+/.test(line) || /^>\s?/.test(line) || /^\d+\.\s+/.test(line) || /^[-*]\s+/.test(line);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (/^```/.test(line)) {
      const lang = line.replace(/^```/, "").trim();
      i += 1;
      const codeLines = [];
      while (i < lines.length && !/^```/.test(lines[i])) {
        codeLines.push(lines[i]);
        i += 1;
      }
      if (i < lines.length && /^```/.test(lines[i])) i += 1;
      blocks.push({ type: "code", lang, code: codeLines.join("\n").trimEnd() });
      continue;
    }
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      blocks.push({ type: "heading", level: headingMatch[1].length, text: headingMatch[2] });
      i += 1;
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quoteLines = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i += 1;
      }
      blocks.push({ type: "quote", lines: quoteLines });
      continue;
    }
    const ordered = line.match(/^(\d+)\.\s+(.+)$/);
    if (ordered) {
      const items = [];
      const start = Number(ordered[1]) || 1;
      while (i < lines.length) {
        const m2 = lines[i].match(/^\d+\.\s+(.+)$/);
        if (!m2) break;
        items.push(m2[1]);
        i += 1;
      }
      blocks.push({ type: "ol", start, items });
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length) {
        const m2 = lines[i].match(/^[-*]\s+(.+)$/);
        if (!m2) break;
        items.push(m2[1]);
        i += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
      para.push(lines[i].trim());
      i += 1;
    }
    blocks.push({ type: "paragraph", text: para.join(" ") });
  }
  return blocks;
}
function InlineText({ text }) {
  const src = String(text || "");
  const nodes = [];
  const re2 = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\((https?:\/\/[^\s)]+)\))/g;
  let last = 0;
  let match;
  while ((match = re2.exec(src)) !== null) {
    if (match.index > last) {
      nodes.push(src.slice(last, match.index));
    }
    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      nodes.push(/* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: token.slice(2, -2) }, `b-${match.index}`));
    } else if (token.startsWith("*") && token.endsWith("*")) {
      nodes.push(/* @__PURE__ */ jsxRuntimeExports.jsx("em", { children: token.slice(1, -1) }, `i-${match.index}`));
    } else if (token.startsWith("`") && token.endsWith("`")) {
      nodes.push(/* @__PURE__ */ jsxRuntimeExports.jsx("code", { className: "kc-inline-code", children: token.slice(1, -1) }, `c-${match.index}`));
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      if (linkMatch) {
        nodes.push(
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "a",
            {
              href: linkMatch[2],
              target: "_blank",
              rel: "noreferrer",
              className: "kc-md-link",
              children: linkMatch[1]
            },
            `a-${match.index}`
          )
        );
      } else {
        nodes.push(token);
      }
    }
    last = match.index + token.length;
  }
  if (last < src.length) nodes.push(src.slice(last));
  return /* @__PURE__ */ jsxRuntimeExports.jsx(jsxRuntimeExports.Fragment, { children: nodes });
}
function CodeBlock({ lang, code }) {
  const [copied, setCopied] = reactExports.useState(false);
  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-code-block", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-code-header", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-code-lang", children: lang || "code" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-code-copy", onClick: copy, children: copied ? "✓ copied" : "⧉ copy" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "kc-code-body", children: /* @__PURE__ */ jsxRuntimeExports.jsx("code", { children: code }) })
  ] });
}
function formatTs(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (_2) {
    return "";
  }
}
function AgentApprovalModal({ ctx, value, onChange, onSend, onQuickReply, onSkillApprove, onStop, onDismiss }) {
  const inputRef = reactExports.useRef(null);
  const [showSuggest, setShowSuggest] = reactExports.useState(false);
  const [approvalNote, setApprovalNote] = reactExports.useState("");
  const [approvalBusy, setApprovalBusy] = reactExports.useState("");
  const [approvalError, setApprovalError] = reactExports.useState("");
  const approvalRequest = ctx?.approvalRequest && typeof ctx.approvalRequest === "object" ? ctx.approvalRequest : {};
  const approvalActions = approvalRequest.actions && typeof approvalRequest.actions === "object" ? approvalRequest.actions : {};
  const approvalMetadata = approvalRequest.metadata && typeof approvalRequest.metadata === "object" ? approvalRequest.metadata : {};
  const isSkillApproval2 = String(ctx?.kind || "").toLowerCase() === "skill_approval" || String(approvalMetadata.approval_mode || "").toLowerCase() === "skill_permission_grant";
  reactExports.useEffect(() => {
    if (showSuggest) inputRef.current?.focus();
  }, [showSuggest]);
  reactExports.useEffect(() => {
    setApprovalNote("");
    setApprovalBusy("");
    setApprovalError("");
    setShowSuggest(false);
  }, [ctx?.runId, ctx?.scope, ctx?.kind]);
  const handleKey = (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      onSend();
    }
    if (e.key === "Escape") onDismiss();
  };
  const handleSkillApproval = async (scope) => {
    if (!onSkillApprove) return;
    setApprovalBusy(scope);
    setApprovalError("");
    try {
      await onSkillApprove(scope, approvalNote);
    } catch (err) {
      setApprovalError(err.message || "Approval failed.");
    } finally {
      setApprovalBusy("");
    }
  };
  const suggestedScopes = Array.isArray(approvalMetadata.suggested_scopes) && approvalMetadata.suggested_scopes.length ? approvalMetadata.suggested_scopes : ["once", "session", "always"];
  const scopeLabels = {
    once: "Allow once",
    session: "Allow this session",
    always: "Always allow"
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-modal-overlay", onClick: (e) => {
    if (!isSkillApproval2 && e.target === e.currentTarget) onDismiss();
  }, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-modal", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-modal-header", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-modal-icon", children: isSkillApproval2 ? "🛡️" : "⏳" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-modal-title", children: approvalRequest.title || (isSkillApproval2 ? "Skill permission required" : "Agent is waiting for your input") }),
      !isSkillApproval2 && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-modal-close", onClick: onDismiss, children: "✕" })
    ] }),
    (approvalRequest.summary || ctx.prompt) && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-modal-prompt", children: /* @__PURE__ */ jsxRuntimeExports.jsx(MarkdownRenderer, { content: approvalRequest.summary || ctx.prompt }) }),
    Array.isArray(approvalRequest.sections) && approvalRequest.sections.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-approval-sections", children: approvalRequest.sections.map((section, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-approval-section", children: [
      section.title && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-approval-section-title", children: section.title }),
      Array.isArray(section.items) && section.items.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("ul", { className: "kc-approval-list", children: section.items.map((item, itemIndex) => /* @__PURE__ */ jsxRuntimeExports.jsx("li", { children: item }, `${index2}-${itemIndex}`)) })
    ] }, `${section.title || "section"}-${index2}`)) }),
    approvalRequest.help_text && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-approval-help", children: approvalRequest.help_text }),
    isSkillApproval2 ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-approval-note-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "kc-approval-label", children: "Approval note" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "textarea",
          {
            className: "kc-modal-input",
            placeholder: "Optional note for the audit log",
            value: approvalNote,
            onChange: (e) => setApprovalNote(e.target.value),
            rows: 2
          }
        )
      ] }),
      approvalError && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-approval-error", children: [
        "⚠ ",
        approvalError
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-modal-quick kc-modal-quick--stacked", children: [
        suggestedScopes.map((scope) => /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "kc-modal-quick-btn kc-modal-quick-btn--approve",
            onClick: () => handleSkillApproval(scope),
            disabled: !!approvalBusy,
            children: approvalBusy === scope ? "Approving…" : scopeLabels[scope] || `Approve (${scope})`
          },
          scope
        )),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-modal-quick-btn kc-modal-quick-btn--reject", onClick: onStop, children: "Stop run" })
      ] })
    ] }) : /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-modal-quick", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-modal-quick-btn kc-modal-quick-btn--approve", onClick: () => onQuickReply("approve"), children: approvalActions.accept_label || "Approve" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: `kc-modal-quick-btn kc-modal-quick-btn--suggest${showSuggest ? " kc-modal-quick-btn--active" : ""}`,
            onClick: () => {
              setShowSuggest((v2) => !v2);
              onChange("");
            },
            children: approvalActions.suggest_label || "Suggest"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-modal-quick-btn kc-modal-quick-btn--reject", onClick: () => onQuickReply("cancel"), children: approvalActions.reject_label || "Reject" })
      ] }),
      showSuggest && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-modal-input-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "textarea",
          {
            ref: inputRef,
            className: "kc-modal-input",
            placeholder: "Type your suggestion… (Ctrl+Enter to send)",
            value,
            onChange: (e) => onChange(e.target.value),
            onKeyDown: handleKey,
            rows: 3
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "kc-modal-send",
            onClick: onSend,
            disabled: !value.trim(),
            children: /* @__PURE__ */ jsxRuntimeExports.jsx(SendIcon$1, {})
          }
        )
      ] })
    ] })
  ] }) });
}
function SendIcon$1() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("line", { x1: "22", y1: "2", x2: "11", y2: "13" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("polygon", { points: "22 2 15 22 11 13 2 9 22 2" })
  ] });
}
function ClearIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "14", height: "14", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("polyline", { points: "3 6 5 6 21 6" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M19 6l-1 14H6L5 6" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M10 11v6M14 11v6" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M9 6V4h6v2" })
  ] });
}
function HistoryIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "12", cy: "12", r: "10" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("polyline", { points: "12 6 12 12 16 14" })
  ] });
}
function ClockIcon({ size = 14 }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "12", cy: "12", r: "10" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("polyline", { points: "12 6 12 12 16 14" })
  ] });
}
function PaperclipIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.9", strokeLinecap: "round", strokeLinejoin: "round", children: /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "m21.4 11.1-8.49 8.49a5 5 0 0 1-7.07-7.07l9.19-9.2a3.5 3.5 0 1 1 4.95 4.96L10.76 17.5a2 2 0 1 1-2.83-2.83l8.49-8.48" }) });
}
function FolderIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.9", strokeLinecap: "round", strokeLinejoin: "round", children: /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M3 7.5A1.5 1.5 0 0 1 4.5 6h4l1.5 2h7.5A1.5 1.5 0 0 1 19 9.5v7a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 16.5z" }) });
}
function PlanModeIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.9", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M8 6h11" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M8 12h11" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M8 18h11" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "4", cy: "6", r: "1" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "4", cy: "12", r: "1" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "4", cy: "18", r: "1" })
  ] });
}
function AgentModeIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.9", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M12 3v3" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M7 6h10" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("rect", { x: "5", y: "9", width: "14", height: "9", rx: "3" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M9 13h.01" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M15 13h.01" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M9.5 16h5" })
  ] });
}
function ResearchModeIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.9", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "11", cy: "11", r: "6" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "m20 20-3.5-3.5" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M11 8v3l2 2" })
  ] });
}
function PlugModeIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.9", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M9 7V3" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M15 7V3" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M7 9h10" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M8 9v3a4 4 0 0 0 8 0V9" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M12 16v5" })
  ] });
}
function HistoryList({ sessions, onLoad, onDelete }) {
  if (sessions.length === 0) {
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-history-empty", children: [
      "No past conversations yet.",
      /* @__PURE__ */ jsxRuntimeExports.jsx("br", {}),
      "Start a new chat and it will appear here."
    ] });
  }
  const todayStart = new Date((/* @__PURE__ */ new Date()).setHours(0, 0, 0, 0)).getTime();
  const yesterdayStart = todayStart - 864e5;
  const weekStart = todayStart - 6 * 864e5;
  const groups = { Today: [], Yesterday: [], "Last 7 days": [], Older: [] };
  sessions.slice().reverse().forEach((s) => {
    const ts = new Date(s.updatedAt || s.createdAt).getTime();
    if (ts >= todayStart) groups["Today"].push(s);
    else if (ts >= yesterdayStart) groups["Yesterday"].push(s);
    else if (ts >= weekStart) groups["Last 7 days"].push(s);
    else groups["Older"].push(s);
  });
  return /* @__PURE__ */ jsxRuntimeExports.jsx(jsxRuntimeExports.Fragment, { children: ["Today", "Yesterday", "Last 7 days", "Older"].map(
    (label) => groups[label].length === 0 ? null : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-history-group-label", children: label }),
      groups[label].map((s) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-history-item", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "kc-history-item-btn", onClick: () => onLoad(s), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-history-item-title", children: s.title }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-history-item-time", children: formatRelTime(s.updatedAt || s.createdAt) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-history-item-del", title: "Delete", onClick: (e) => {
          e.stopPropagation();
          onDelete(s.id);
        }, children: "×" })
      ] }, s.id))
    ] }, label)
  ) });
}
const SESSIONS_KEY = "kendr_sessions_v1";
const CURRENT_HIST_KEY = "kendr_chat_history_v1";
const PROVIDERS = [
  { id: "openai", label: "OpenAI", settingsKey: "openaiKey", defaultModel: "openai/gpt-4o-mini" },
  { id: "anthropic", label: "Anthropic", settingsKey: "anthropicKey", defaultModel: "anthropic/claude-sonnet-4-6" },
  { id: "google", label: "Google AI", settingsKey: "googleKey", defaultModel: "google/gemini-2.0-flash" },
  { id: "xai", label: "xAI / Grok", settingsKey: "xaiKey", defaultModel: "xai/grok-4" }
];
const CLOUD_MODEL_CATALOG = {
  openai: [
    { name: "gpt-5.4", badge: "latest" },
    { name: "gpt-5.2", badge: "agent" },
    { name: "gpt-4o", badge: "best" },
    { name: "gpt-4o-mini", badge: "cheapest" },
    { name: "gpt-4-turbo" }
  ],
  anthropic: [
    { name: "claude-opus-4-6", badge: "best" },
    { name: "claude-sonnet-4-6", badge: "latest" },
    { name: "claude-haiku-4-5", badge: "cheapest" }
  ],
  google: [
    { name: "gemini-2.5-pro", badge: "best" },
    { name: "gemini-2.5-flash", badge: "agent" },
    { name: "gemini-2.0-flash", badge: "latest" },
    { name: "gemini-1.5-pro" }
  ],
  xai: [
    { name: "grok-4", badge: "best" },
    { name: "grok-4-1-fast-reasoning", badge: "agent" },
    { name: "grok-4.20-beta-latest-non-reasoning", badge: "latest" }
  ]
};
const STUDIO_NAV_ITEMS = [
  { id: "build", label: "Build" },
  { id: "memory", label: "Memory" },
  { id: "integrations", label: "Integrations" },
  { id: "runs", label: "Runs" },
  { id: "settings", label: "Settings" },
  { id: "about", label: "About Kendr" }
];
function lsGet(key) {
  try {
    return JSON.parse(localStorage.getItem(key));
  } catch {
    return null;
  }
}
function lsSet(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
  }
}
function readSessions(settings) {
  const all = lsGet(SESSIONS_KEY) || [];
  const days = settings?.chatHistoryRetentionDays ?? 14;
  if (!days || days <= 0) return all.slice().reverse();
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1e3;
  return all.filter((session) => new Date(session.updatedAt || session.createdAt).getTime() >= cutoff).reverse();
}
function saveCurrentAsSession(chatId) {
  const messages = lsGet(CURRENT_HIST_KEY) || [];
  if (!messages.length) return;
  const first = messages.find((item) => item.role === "user");
  const title = String(first?.content || "").slice(0, 60) || "New conversation";
  const all = lsGet(SESSIONS_KEY) || [];
  const session = {
    id: chatId,
    title,
    createdAt: String(messages[0]?.ts || (/* @__PURE__ */ new Date()).toISOString()),
    updatedAt: (/* @__PURE__ */ new Date()).toISOString(),
    messages
  };
  lsSet(SESSIONS_KEY, [...all.filter((item) => item.id !== chatId), session].slice(-100));
}
function sessionRelTime(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  if (diff < 6e4) return "just now";
  if (diff < 36e5) return `${Math.floor(diff / 6e4)}m ago`;
  if (diff < 864e5) return `${Math.floor(diff / 36e5)}h ago`;
  const d = new Date(dateStr);
  return d.toLocaleDateString(void 0, { month: "short", day: "numeric" });
}
function buildProviderModels(providerId, status) {
  const selectable = Array.isArray(status?.selectable_models) ? status.selectable_models : [];
  const details = Array.isArray(status?.selectable_model_details) ? status.selectable_model_details : [];
  const detailMap = new Map(details.map((item) => [String(item?.name || "").trim(), item]));
  const catalog = Array.isArray(CLOUD_MODEL_CATALOG[providerId]) ? CLOUD_MODEL_CATALOG[providerId] : [];
  const seen2 = /* @__PURE__ */ new Set();
  const merged = [];
  for (const entry of catalog) {
    const name = String(entry?.name || "").trim();
    if (!name) continue;
    seen2.add(name);
    merged.push({
      name,
      badge: String(entry?.badge || "").trim(),
      available: selectable.includes(name),
      agentCapable: detailMap.get(name)?.agent_capable
    });
  }
  for (const name of selectable) {
    const clean = String(name || "").trim();
    if (!clean || seen2.has(clean)) continue;
    const detail = detailMap.get(clean);
    merged.push({
      name: clean,
      badge: "",
      available: true,
      agentCapable: detail?.agent_capable
    });
  }
  return merged;
}
function modelLabel(modelId) {
  const raw = String(modelId || "").trim();
  if (!raw) return "Auto model";
  if (raw.startsWith("ollama/")) return raw.replace(/^ollama\//, "");
  const provider = raw.split("/")[0];
  const name = raw.replace(`${provider}/`, "");
  const label = PROVIDERS.find((item) => item.id === provider)?.label || provider;
  return `${label} · ${name}`;
}
function StudioNavIcon({ name }) {
  const common = {
    width: 15,
    height: 15,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true
  };
  switch (name) {
    case "build":
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { ...common, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M3 4.5h10" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M5.5 2.5v4" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M10.5 2.5v4" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M3 7.5h10v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" })
      ] });
    case "memory":
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { ...common, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M5 3.5h6a1 1 0 0 1 1 1v7H4v-7a1 1 0 0 1 1-1z" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M6 2.5v2" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M10 2.5v2" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M6 8h4" })
      ] });
    case "integrations":
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { ...common, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "5", cy: "5", r: "1.5" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "11", cy: "5", r: "1.5" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "8", cy: "11", r: "1.5" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M6.5 5h3" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M5.9 6.2 7.3 9.6" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M10.1 6.2 8.7 9.6" })
      ] });
    case "runs":
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { ...common, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M8 3.25a4.75 4.75 0 1 0 4.58 6" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M9.75 2.75H13v3.25" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M8 5.5v2.75l1.75 1.25" })
      ] });
    case "settings":
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { ...common, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "8", cy: "8", r: "2.25" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M8 2.5v1.25" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M8 12.25v1.25" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M12.25 8h1.25" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M2.5 8h1.25" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "m11.89 4.11.88-.88" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "m3.23 12.77.88-.88" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "m11.89 11.89.88.88" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "m3.23 3.23.88.88" })
      ] });
    default:
      return null;
  }
}
function StudioLayout() {
  const { state, dispatch, refreshModelInventory, refreshOllamaModels } = useApp();
  const [chatKey, setChatKey] = reactExports.useState(0);
  const [chatId, setChatId] = reactExports.useState(() => `chat-${Date.now()}`);
  const [activeSession, setActiveSession] = reactExports.useState(null);
  const [sessions, setSessions] = reactExports.useState(() => readSessions(state.settings));
  const [historyFlyoutOpen, setHistoryFlyoutOpen] = reactExports.useState(false);
  const [profileMenuOpen, setProfileMenuOpen] = reactExports.useState(false);
  const historyFlyoutRef = reactExports.useRef(null);
  const profileMenuRef = reactExports.useRef(null);
  const providerStatuses = reactExports.useMemo(() => Object.fromEntries(
    (state.modelInventory && Array.isArray(state.modelInventory.providers) ? state.modelInventory.providers : []).map((item) => [item.provider, item])
  ), [state.modelInventory]);
  const localModels = Array.isArray(state.ollamaModels) ? state.ollamaModels : [];
  const cloudReady = PROVIDERS.some((provider) => {
    const hasSavedKey = !!String(state.settings?.[provider.settingsKey] || "").trim();
    const status = providerStatuses[provider.id] || {};
    const selectable = Array.isArray(status.selectable_models) ? status.selectable_models : [];
    return hasSavedKey && selectable.length > 0;
  });
  const selectedModelReady = (() => {
    const selected = String(state.selectedModel || "").trim();
    if (!selected) return false;
    if (selected.startsWith("ollama/")) {
      const name = selected.replace(/^ollama\//, "");
      return localModels.some((model) => String(model?.name || model || "").trim() === name);
    }
    const provider = selected.split("/")[0];
    const status = providerStatuses[provider] || {};
    const selectable = Array.isArray(status.selectable_models) ? status.selectable_models : [];
    const modelName = selected.replace(`${provider}/`, "");
    return selectable.includes(modelName);
  })();
  const hasAnyModel = selectedModelReady || cloudReady || localModels.length > 0;
  reactExports.useEffect(() => {
    if (state.selectedModel || cloudReady || localModels.length === 0) return;
    const firstLocal = String(localModels[0]?.name || localModels[0] || "").trim();
    if (!firstLocal) return;
    dispatch({ type: "SET_MODEL", model: `ollama/${firstLocal}` });
  }, [cloudReady, dispatch, localModels, state.selectedModel]);
  reactExports.useEffect(() => {
    setSessions(readSessions(state.settings));
  }, [chatKey, state.settings]);
  reactExports.useEffect(() => {
    if (!historyFlyoutOpen) return void 0;
    const onMouseDown = (event) => {
      if (historyFlyoutRef.current && !historyFlyoutRef.current.contains(event.target)) setHistoryFlyoutOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [historyFlyoutOpen]);
  reactExports.useEffect(() => {
    if (!profileMenuOpen) return void 0;
    const onMouseDown = (event) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(event.target)) setProfileMenuOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [profileMenuOpen]);
  reactExports.useEffect(() => {
    setHistoryFlyoutOpen(false);
    setProfileMenuOpen(false);
  }, [state.sidebarOpen]);
  const handleNewChat = () => {
    saveCurrentAsSession(chatId);
    lsSet(CURRENT_HIST_KEY, []);
    const newId = `chat-${Date.now()}`;
    setChatId(newId);
    setActiveSession(null);
    setChatKey((value) => value + 1);
    setHistoryFlyoutOpen(false);
  };
  const handleLoadSession = (session) => {
    saveCurrentAsSession(chatId);
    const all = lsGet(SESSIONS_KEY) || [];
    lsSet(SESSIONS_KEY, all.filter((item) => item.id !== session.id));
    lsSet(CURRENT_HIST_KEY, session.messages);
    setChatId(session.id);
    setActiveSession(session);
    setChatKey((value) => value + 1);
    setHistoryFlyoutOpen(false);
  };
  const handleDeleteSession = (id2) => {
    const all = lsGet(SESSIONS_KEY) || [];
    lsSet(SESSIONS_KEY, all.filter((item) => item.id !== id2));
    setSessions((current) => current.filter((item) => item.id !== id2));
    if (activeSession?.id === id2) setActiveSession(null);
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-minimal-root", children: hasAnyModel ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-minimal-shell", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `sl-studio-shell ${state.sidebarOpen ? "" : "sl-studio-shell--collapsed"}`, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("aside", { className: `sl-studio-sidebar ${state.sidebarOpen ? "" : "sl-studio-sidebar--collapsed"}`, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-studio-side-top", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "sl-studio-collapse",
            onClick: () => dispatch({ type: "TOGGLE_SIDEBAR" }),
            title: state.sidebarOpen ? "Collapse sidebar" : "Expand sidebar",
            children: state.sidebarOpen ? "‹" : "›"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: `sl-studio-new ${state.sidebarOpen ? "" : "sl-studio-new--icon"}`, onClick: handleNewChat, title: "New chat", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-studio-new-mark", children: "+" }),
          state.sidebarOpen && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "New chat" })
        ] })
      ] }),
      state.sidebarOpen ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-studio-session-list", children: sessions.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-studio-empty", children: "No saved chats yet" }) : sessions.map((session) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-studio-session-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: `sl-studio-session ${activeSession?.id === session.id ? "active" : ""}`, onClick: () => handleLoadSession(session), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-studio-session-title", children: session.title }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-studio-session-time", children: sessionRelTime(session.updatedAt || session.createdAt) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "sl-studio-session-del", onClick: () => handleDeleteSession(session.id), children: "×" })
      ] }, session.id)) }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-studio-mini-list", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-history-flyout-root", ref: historyFlyoutRef, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: `sl-studio-mini-session ${historyFlyoutOpen ? "active" : ""}`,
            onClick: () => setHistoryFlyoutOpen((value) => !value),
            title: "Chat history",
            children: /* @__PURE__ */ jsxRuntimeExports.jsx(ChatThreadsIcon, {})
          }
        ),
        historyFlyoutOpen && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-history-flyout", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-history-flyout-title", children: "Chats" }),
          sessions.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-history-flyout-empty", children: "No saved chats yet" }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-history-flyout-list", children: sessions.map((session) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-history-flyout-row", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "sl-history-flyout-item", onClick: () => handleLoadSession(session), children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-history-flyout-item-title", children: session.title }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-history-flyout-item-time", children: sessionRelTime(session.updatedAt || session.createdAt) })
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "sl-history-flyout-del", onClick: () => handleDeleteSession(session.id), children: "×" })
          ] }, session.id)) })
        ] })
      ] }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-studio-side-bottom", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-profile-menu-root", ref: profileMenuRef, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs(
          "button",
          {
            className: `sl-profile-trigger ${profileMenuOpen ? "active" : ""}`,
            onClick: () => setProfileMenuOpen((value) => !value),
            title: "Workspace menu",
            children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-profile-avatar", children: "K" }),
              state.sidebarOpen && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "sl-profile-copy", children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-profile-name", children: "Workspace menu" }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-profile-sub", children: "Build, runs, memory, settings" })
              ] }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-profile-caret", children: "⌄" })
            ]
          }
        ),
        profileMenuOpen && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `sl-profile-menu ${state.sidebarOpen ? "" : "sl-profile-menu--collapsed"}`, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-profile-menu-header", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-profile-avatar sl-profile-avatar--lg", children: "K" }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-profile-menu-copy", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-profile-menu-title", children: "Kendr workspace" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-profile-menu-sub", children: "Open a focused surface, then jump back to search in one click." })
            ] })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-profile-menu-list", children: STUDIO_NAV_ITEMS.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs(
            "button",
            {
              className: "sl-profile-menu-item",
              onClick: () => {
                dispatch({ type: "SET_VIEW", view: item.id });
                setProfileMenuOpen(false);
              },
              children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-studio-nav-icon", children: /* @__PURE__ */ jsxRuntimeExports.jsx(StudioNavIcon, { name: item.id }) }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-profile-menu-item-label", children: item.label }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-profile-menu-item-arrow", children: "›" })
              ]
            },
            item.id
          )) })
        ] })
      ] }) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-studio-main", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-studio-stage", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      ChatPanel,
      {
        fullWidth: true,
        hideHeader: true,
        studioMode: true,
        minimalStudio: true,
        studioAccessory: /* @__PURE__ */ jsxRuntimeExports.jsx(
          StudioModelPicker,
          {
            state,
            dispatch,
            providerStatuses,
            localModels,
            refreshOllamaModels
          }
        )
      },
      chatKey
    ) }) })
  ] }) }) : /* @__PURE__ */ jsxRuntimeExports.jsx(
    StudioModelGate,
    {
      state,
      dispatch,
      localModels,
      refreshModelInventory,
      refreshOllamaModels
    }
  ) });
}
function ChatThreadsIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M3 4.5h10a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H8.5l-2.5 2v-2H3a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1z" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M5 7h6" })
  ] });
}
function StudioModelPicker({ state, dispatch, providerStatuses, localModels, refreshOllamaModels }) {
  const [open, setOpen] = reactExports.useState(false);
  const rootRef = reactExports.useRef(null);
  const triggerRef = reactExports.useRef(null);
  const [dropdownStyle, setDropdownStyle] = reactExports.useState(null);
  const selected = String(state.selectedModel || "").trim();
  const selectedProvider = selected.startsWith("ollama/") ? "ollama" : String(selected.split("/")[0] || "").trim().toLowerCase();
  const selectedAvailable = (() => {
    if (!selected) return true;
    if (selected.startsWith("ollama/")) {
      const localName = selected.replace(/^ollama\//, "");
      return localModels.some((model2) => String(model2?.name || model2 || "").trim() === localName);
    }
    const provider = selected.split("/")[0];
    const model = selected.replace(`${provider}/`, "");
    const status = providerStatuses[provider] || {};
    const selectable = Array.isArray(status.selectable_models) ? status.selectable_models : [];
    return selectable.includes(model);
  })();
  reactExports.useEffect(() => {
    if (!open) return void 0;
    const onMouseDown = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open]);
  reactExports.useLayoutEffect(() => {
    if (!open) return void 0;
    const updateDropdownPosition = () => {
      const trigger = triggerRef.current;
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const margin = 16;
      const gap = 8;
      const width = Math.min(420, Math.max(280, viewportWidth - margin * 2));
      const left = Math.max(margin, Math.min(rect.left, viewportWidth - width - margin));
      const spaceBelow = viewportHeight - rect.bottom - gap - margin;
      const spaceAbove = rect.top - gap - margin;
      const openUpward = spaceBelow < 260 && spaceAbove > spaceBelow;
      const maxHeight = Math.max(180, openUpward ? spaceAbove : spaceBelow);
      setDropdownStyle({
        position: "fixed",
        left: `${left}px`,
        width: `${width}px`,
        maxHeight: `${maxHeight}px`,
        [openUpward ? "bottom" : "top"]: `${Math.round(openUpward ? viewportHeight - rect.top + gap : rect.bottom + gap)}px`,
        [openUpward ? "top" : "bottom"]: "auto"
      });
    };
    updateDropdownPosition();
    window.addEventListener("resize", updateDropdownPosition);
    window.addEventListener("scroll", updateDropdownPosition, true);
    return () => {
      window.removeEventListener("resize", updateDropdownPosition);
      window.removeEventListener("scroll", updateDropdownPosition, true);
    };
  }, [open]);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mp-root sl-model-picker", ref: rootRef, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "button",
      {
        ref: triggerRef,
        className: `mp-trigger${selected && !selectedAvailable ? " mp-trigger--warn" : ""}`,
        onClick: () => setOpen((value) => !value),
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `mp-provider-dot ${selectedProvider || "auto"}` }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mp-trigger-label", children: modelLabel(selected) }),
          selected && !selectedAvailable && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mp-trigger-warn", children: "Locked" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-model-trigger-caret", children: "⌄" })
        ]
      }
    ),
    open && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mp-dropdown", style: dropdownStyle || void 0, children: [
      PROVIDERS.map((provider) => {
        const status = providerStatuses[provider.id] || {};
        const hasKey = !!String(state.settings?.[provider.settingsKey] || "").trim();
        const tone = status?.checking ? "checking" : status?.error ? "error" : hasKey ? "ok" : "missing";
        const toneLabel = status?.checking ? "Checking" : status?.error ? "Error" : hasKey ? "Ready" : "Locked";
        const models = buildProviderModels(provider.id, status);
        return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mp-group", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mp-group-label mp-group-label--row", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `mp-provider-dot ${provider.id}` }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: provider.label }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `mp-key-badge ${tone}`, children: toneLabel })
          ] }),
          models.map((entry) => {
            const name = String(entry.name || "").trim();
            const id2 = `${provider.id}/${name}`;
            const disabled = !entry.available;
            return /* @__PURE__ */ jsxRuntimeExports.jsxs(
              "button",
              {
                className: `mp-option ${selected === id2 ? "active" : ""}${disabled ? " mp-option--dim" : ""}`,
                disabled,
                onClick: () => {
                  if (disabled) return;
                  dispatch({ type: "SET_MODEL", model: id2 });
                  setOpen(false);
                },
                children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mp-option-name", children: name }),
                  entry.badge && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `mp-model-badge ${entry.badge}`, children: entry.badge }),
                  typeof entry.agentCapable === "boolean" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `mp-model-badge ${entry.agentCapable ? "agent" : "noagent"}`, children: entry.agentCapable ? "agent" : "text" }),
                  disabled ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mp-lock", children: "🔒" }) : selected === id2 ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mp-option-check", children: "✓" }) : null
                ]
              },
              id2
            );
          })
        ] }, provider.id);
      }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mp-group", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mp-group-label mp-group-label--row", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mp-provider-dot ollama" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Local models" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "mp-refresh-btn", onClick: () => refreshOllamaModels(true), children: "↻" })
        ] }),
        localModels.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mp-empty", children: "No local models found." }) : localModels.map((model) => {
          const name = String(model?.name || model || "").trim();
          const id2 = `ollama/${name}`;
          return /* @__PURE__ */ jsxRuntimeExports.jsxs(
            "button",
            {
              className: `mp-option ${selected === id2 ? "active" : ""}`,
              onClick: () => {
                dispatch({ type: "SET_MODEL", model: id2 });
                setOpen(false);
              },
              children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mp-option-name", children: name }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mp-model-badge agent", children: "local" }),
                selected === id2 && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mp-option-check", children: "✓" })
              ]
            },
            id2
          );
        })
      ] })
    ] })
  ] });
}
function StudioModelGate({ state, dispatch, localModels, refreshModelInventory, refreshOllamaModels }) {
  const api = window.kendrAPI;
  const [setupMode, setSetupMode] = reactExports.useState("api");
  const [providerId, setProviderId] = reactExports.useState("openai");
  const [apiKey, setApiKey] = reactExports.useState("");
  const [saving, setSaving] = reactExports.useState(false);
  const [error, setError] = reactExports.useState("");
  const selectedProvider = PROVIDERS.find((item) => item.id === providerId) || PROVIDERS[0];
  const saveProvider = async () => {
    const value = String(apiKey || "").trim();
    if (!value) {
      setError("Enter an API key first.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api?.settings.set(selectedProvider.settingsKey, value);
      dispatch({ type: "SET_SETTINGS", settings: { [selectedProvider.settingsKey]: value } });
      if (state.backendStatus === "running") {
        await api?.backend.restart();
      } else {
        await api?.backend.start();
      }
      await refreshModelInventory(true);
      dispatch({ type: "SET_MODEL", model: selectedProvider.defaultModel });
    } catch (err) {
      setError(String(err?.message || err || "Could not save provider key."));
    } finally {
      setSaving(false);
    }
  };
  const selectLocalModel = async (model) => {
    const name = String(model?.name || model || "").trim();
    if (!name) return;
    dispatch({ type: "SET_MODEL", model: `ollama/${name}` });
    if (state.backendStatus !== "running") {
      await api?.backend.start().catch(() => {
      });
    }
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-gate", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-gate-card", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-gate-badge", children: "First step" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("h1", { className: "sl-gate-title", children: "Connect one model to start" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "sl-gate-copy", children: "Start with one cloud API key or one local model. Everything else stays tucked into the menu until you need it." }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-gate-tabs", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `sl-gate-tab ${setupMode === "api" ? "active" : ""}`, onClick: () => setSetupMode("api"), children: "Use API key" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `sl-gate-tab ${setupMode === "local" ? "active" : ""}`, onClick: () => {
        setSetupMode("local");
        refreshOllamaModels(true);
      }, children: "Use local model" })
    ] }),
    setupMode === "api" ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-gate-form", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-gate-provider-row", children: PROVIDERS.map((provider) => /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: `sl-gate-provider ${provider.id === providerId ? "active" : ""}`,
          onClick: () => setProviderId(provider.id),
          children: provider.label
        },
        provider.id
      )) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "input",
        {
          className: "sl-gate-input",
          type: "password",
          placeholder: `Paste ${selectedProvider.label} API key`,
          value: apiKey,
          onChange: (event) => setApiKey(event.target.value),
          onKeyDown: (event) => event.key === "Enter" && !saving && saveProvider()
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-gate-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "sl-gate-cta", disabled: saving || !apiKey.trim(), onClick: saveProvider, children: saving ? "Connecting…" : "Save and continue" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "sl-gate-link", onClick: () => dispatch({ type: "SET_VIEW", view: "settings" }), children: "Open full settings" })
      ] })
    ] }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-gate-form", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-gate-inline-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "sl-gate-link", onClick: () => refreshOllamaModels(true), children: "Refresh local models" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "sl-gate-link", onClick: () => dispatch({ type: "SET_VIEW", view: "settings" }), children: "Open model manager" })
      ] }),
      localModels.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-gate-empty", children: "No local models found yet. Pull one from the model manager, then come back here." }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-gate-local-list", children: localModels.map((model) => {
        const name = String(model?.name || model || "").trim();
        const size = model?.size ? `${(Number(model.size) / 1e9).toFixed(1)} GB` : "";
        return /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "sl-gate-local-item", onClick: () => selectLocalModel(model), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-gate-local-name", children: name }),
          size && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "sl-gate-local-size", children: size })
        ] }, name);
      }) })
    ] }),
    !!error && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-gate-error", children: error })
  ] }) });
}
const STATUS_COLOR = {
  completed: "#89d185",
  running: "#3794ff",
  error: "#f47067",
  failed: "#f47067",
  cancelled: "#858585",
  pending: "#cca700",
  awaiting_user_input: "#e3b341"
};
function formatDuration$1(totalSeconds) {
  const s = Math.max(0, Number(totalSeconds) || 0);
  const h2 = Math.floor(s / 3600);
  const m2 = Math.floor(s % 3600 / 60);
  const sec = s % 60;
  if (h2 > 0) return `${h2}h ${m2}m ${sec}s`;
  if (m2 > 0) return `${m2}m ${sec}s`;
  return `${sec}s`;
}
function normalizeRunStatus$1(status) {
  const raw = String(status || "").trim().toLowerCase();
  if (raw === "streaming") return "running";
  if (raw === "awaiting") return "awaiting";
  if (raw === "done") return "completed";
  if (raw === "error") return "failed";
  return raw || "running";
}
function isShellProgressItem$1(item) {
  if (!item || typeof item !== "object") return false;
  const kind = String(item.kind || "").toLowerCase();
  const title = String(item.title || "").toLowerCase();
  const detail = String(item.detail || "").toLowerCase();
  const command = String(item.command || "").trim();
  if (command) return true;
  if (kind.includes("command") || kind.includes("shell")) return true;
  return /\bshell command\b|\brunning command\b|\bos[_\s-]?agent\b/.test(`${title} ${detail}`);
}
function AgentOrchestration() {
  const { state, dispatch, openFile } = useApp();
  const [tab, setTab] = reactExports.useState("activity");
  const [runs, setRuns] = reactExports.useState([]);
  const [selected, setSelected] = reactExports.useState(null);
  const [runDetail, setRunDetail] = reactExports.useState(null);
  const [loading, setLoading] = reactExports.useState(false);
  const [diffPreviewPath, setDiffPreviewPath] = reactExports.useState("");
  const backendUrl = state.backendUrl || "http://127.0.0.1:2151";
  const activityFeed = Array.isArray(state.activityFeed) ? state.activityFeed : [];
  const fetchRuns = reactExports.useCallback(async () => {
    try {
      const response = await fetch(`${backendUrl}/api/runs`);
      if (!response.ok) return;
      const data = await response.json();
      const list = Array.isArray(data) ? data : data.runs || [];
      setRuns(list);
      dispatch({ type: "SET_RUNS", runs: list });
    } catch (_2) {
    }
  }, [backendUrl, dispatch]);
  const fetchDetail = reactExports.useCallback(async (runId) => {
    if (!runId) return;
    setLoading(true);
    try {
      const [runRes, artifactsRes, messagesRes] = await Promise.all([
        fetch(`${backendUrl}/api/runs/${runId}`).then((response) => response.json()).catch(() => null),
        fetch(`${backendUrl}/api/runs/${runId}/artifacts`).then((response) => response.json()).catch(() => []),
        fetch(`${backendUrl}/api/runs/${runId}/messages`).then((response) => response.json()).catch(() => [])
      ]);
      setRunDetail({
        run: runRes,
        artifacts: Array.isArray(artifactsRes) ? artifactsRes : [],
        messages: Array.isArray(messagesRes) ? messagesRes : []
      });
    } catch (_2) {
      setRunDetail(null);
    }
    setLoading(false);
  }, [backendUrl]);
  reactExports.useEffect(() => {
    if (tab !== "debug") return;
    fetchRuns();
    const id2 = setInterval(fetchRuns, 5e3);
    return () => clearInterval(id2);
  }, [fetchRuns, tab]);
  reactExports.useEffect(() => {
    if (tab === "debug" && selected) fetchDetail(selected);
  }, [selected, fetchDetail, tab]);
  const stopRun = async (runId) => {
    await fetch(`${backendUrl}/api/runs/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId })
    }).catch(() => {
    });
    fetchRuns();
  };
  const deleteRun = async (runId) => {
    await fetch(`${backendUrl}/api/runs/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId })
    }).catch(() => {
    });
    fetchRuns();
    if (selected === runId) {
      setSelected(null);
      setRunDetail(null);
    }
  };
  const inspectRun = reactExports.useCallback((runId) => {
    if (!runId) return;
    setTab("debug");
    setSelected(runId);
  }, []);
  const openActivityItem = reactExports.useCallback(async (item) => {
    const filePath = String(item?.path || "").trim();
    if (!filePath) return;
    dispatch({ type: "SET_VIEW", view: "developer" });
    await openFile(filePath);
  }, [dispatch, openFile]);
  const reviewActivityItem = reactExports.useCallback((item) => {
    const filePath = String(item?.path || "").trim();
    if (!filePath) return;
    setDiffPreviewPath(filePath);
  }, []);
  const recentActivity = reactExports.useMemo(() => activityFeed.slice(0, 16), [activityFeed]);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orchestration-view", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      GitDiffPreview,
      {
        cwd: state.projectRoot,
        filePath: diffPreviewPath,
        onClose: () => setDiffPreviewPath(""),
        onOpenFile: (filePath) => openActivityItem({ path: filePath })
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orch-header", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { className: "orch-title", children: "Agent Orchestration" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orch-header-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orch-tabs", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `orch-tab ${tab === "activity" ? "active" : ""}`, onClick: () => setTab("activity"), children: "Activity" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `orch-tab ${tab === "debug" ? "active" : ""}`, onClick: () => setTab("debug"), children: "Debug" })
        ] }),
        tab === "activity" && recentActivity.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-btn-sm", onClick: () => dispatch({ type: "CLEAR_ACTIVITY_FEED" }), children: "Clear" }),
        tab === "debug" && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "icon-btn", onClick: fetchRuns, title: "Refresh", children: "⟳" })
      ] })
    ] }),
    state.backendStatus !== "running" && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orch-banner", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
        "Backend is ",
        state.backendStatus
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "btn-accent", onClick: () => window.kendrAPI?.backend.start(), children: "Start Backend" })
    ] }),
    tab === "activity" ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "orch-activity", children: recentActivity.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orch-empty", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "No recent activity yet." }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Start a run in Studio or Project mode." })
    ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "orch-activity-feed", children: recentActivity.map((entry) => {
      const progress = Array.isArray(entry.progress) ? entry.progress.filter((item) => !isShellProgressItem$1(item)) : [];
      const cards = summarizeRunArtifacts(progress, entry.artifacts);
      const checklist = Array.isArray(entry.checklist) ? entry.checklist : [];
      const planLike = checklist.length > 0 && (entry.mode === "plan" || isPlanApprovalScope(entry.approvalScope, entry.approvalKind, entry.approvalRequest));
      const latestPath = cards.flatMap((card) => Array.isArray(card.items) ? card.items : []).find((item) => item?.path);
      const elapsedSeconds = entry.runStartedAt ? Math.max(0, Math.floor((Date.now() - new Date(entry.runStartedAt).getTime()) / 1e3)) : 0;
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-head", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-meta", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-activity-source", children: entry.source }),
            entry.modeLabel && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-activity-chip", children: entry.modeLabel }),
            entry.runId && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-activity-chip", children: entry.runId.slice(-8) })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-meta", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `rp-activity-status rp-activity-status--${normalizeRunStatus$1(entry.status)}`, children: normalizeRunStatus$1(entry.status) }),
            entry.runId && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-btn-sm", onClick: () => inspectRun(entry.runId), children: "Inspect" })
          ] })
        ] }),
        !!cards.length && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-grid", children: cards.map((card) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-activity-card kc-activity-card--${card.kind}`, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-activity-card-head", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-kind", children: card.kind }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-title", children: card.title })
            ] }),
            card.kind === "edit" && Array.isArray(card.items) && card.items.some((item) => item?.path) && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-action", onClick: () => reviewActivityItem(card.items.find((item) => item?.path)), children: "Review" })
          ] }),
          Array.isArray(card.items) && card.items.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-items", children: card.items.slice(0, 3).map((item) => item?.path ? /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-item kc-activity-card-item--action", onClick: () => openActivityItem(item), children: item.label }, `${entry.id}-${item.path}-${item.label}`) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-activity-card-item", children: item.label }, `${entry.id}-${item.label}`)) })
        ] }, `${entry.id}-${card.kind}-${card.title}`)) }),
        planLike && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-plan-preview", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "rp-plan-title", children: "Plan" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-list", children: checklist.slice(0, 4).map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-item", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-mark", children: item.done ? "✓" : item.status === "running" ? "…" : "·" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-body", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-row", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-checklist-step", children: [
                item.step,
                "."
              ] }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-checklist-text", children: item.title })
            ] }) })
          ] }, `${entry.id}-${item.step}-${item.title}`)) })
        ] }),
        entry.content && !planLike && !isSkillApproval(entry.approvalKind, entry.approvalRequest) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-content", children: [
          entry.content.slice(0, 320),
          entry.content.length > 320 ? "…" : ""
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-footer", children: [
          entry.runId && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: formatDuration$1(elapsedSeconds) }),
          latestPath?.path && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-btn-sm", onClick: () => openActivityItem(latestPath), children: "Open file" })
        ] })
      ] }, entry.id);
    }) }) }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orch-layout", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orch-list", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "orch-list-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
          "RUNS (",
          runs.length,
          ")"
        ] }) }),
        runs.length === 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orch-empty", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "No runs yet." }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Start a conversation in the chat panel." })
        ] }),
        runs.map((run) => /* @__PURE__ */ jsxRuntimeExports.jsx(
          RunItem,
          {
            run,
            selected: selected === run.run_id,
            onClick: () => setSelected(run.run_id),
            onStop: () => stopRun(run.run_id),
            onDelete: () => deleteRun(run.run_id)
          },
          run.run_id
        ))
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "orch-detail", children: [
        !selected && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "orch-detail-empty", children: /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Select a run to view details" }) }),
        selected && loading && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "orch-loading", children: "Loading…" }),
        selected && !loading && runDetail && /* @__PURE__ */ jsxRuntimeExports.jsx(RunDetail, { detail: runDetail })
      ] })
    ] })
  ] });
}
function RunItem({ run, selected, onClick, onStop, onDelete }) {
  const status = run.status || "pending";
  const color = STATUS_COLOR[status] || "#cccccc";
  const isActive = status === "running";
  const text = (run.text || run.workflow_id || run.run_id || "").slice(0, 60);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `run-list-item ${selected ? "run-list-item--selected" : ""}`, onClick, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "run-item-top", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "run-status-dot", style: { background: color, boxShadow: isActive ? `0 0 6px ${color}` : "none" } }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "run-item-id", children: run.run_id?.slice(0, 12) || "?" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `run-item-status run-status--${status}`, children: status })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "run-item-text", children: text || "(no description)" }),
    run.created_at && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "run-item-date", children: new Date(run.created_at).toLocaleString() }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "run-item-actions", onClick: (event) => event.stopPropagation(), children: [
      isActive && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "run-btn run-btn--stop", onClick: onStop, title: "Stop", children: "■ Stop" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "run-btn run-btn--delete", onClick: onDelete, title: "Delete", children: "✕" })
    ] })
  ] });
}
function RunDetail({ detail }) {
  const { run, artifacts, messages } = detail;
  const [tab, setTab] = reactExports.useState("output");
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "run-detail", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "run-detail-header", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "run-detail-id", children: run?.run_id }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "run-detail-status", style: { color: STATUS_COLOR[run?.status] || "#cccccc" }, children: run?.status })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "run-detail-tabs", children: ["output", "artifacts", "messages"].map((name) => /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "button",
      {
        className: `run-detail-tab ${tab === name ? "active" : ""}`,
        onClick: () => setTab(name),
        children: [
          name.charAt(0).toUpperCase() + name.slice(1),
          name === "artifacts" && artifacts.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "tab-badge", children: artifacts.length })
        ]
      },
      name
    )) }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "run-detail-body", children: [
      tab === "output" && /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "run-output", children: JSON.stringify(run, null, 2) }),
      tab === "artifacts" && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "run-artifacts", children: [
        artifacts.length === 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "detail-empty", children: "No artifacts" }),
        artifacts.map((artifact, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "artifact-item", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "artifact-type", children: artifact.artifact_type || "file" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "artifact-name", children: artifact.name || artifact.path || "artifact" })
        ] }, index2))
      ] }),
      tab === "messages" && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "run-messages", children: [
        messages.length === 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "detail-empty", children: "No messages" }),
        messages.map((message, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `run-msg run-msg--${message.role || "system"}`, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "run-msg-role", children: message.role || "system" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "run-msg-content", children: typeof message.content === "string" ? message.content.slice(0, 200) : JSON.stringify(message.content).slice(0, 200) })
        ] }, index2))
      ] })
    ] })
  ] });
}
function groupBy(arr, key) {
  return arr.reduce((acc, item) => {
    const k2 = item[key] || "Other";
    if (!acc[k2]) acc[k2] = [];
    acc[k2].push(item);
    return acc;
  }, {});
}
function sandboxPresentation(sandbox) {
  const mode = String(sandbox?.mode || "").trim().toLowerCase();
  if (mode === "bubblewrap") return { label: "Sandboxed", tone: "ok" };
  if (mode === "blocked") return { label: "Blocked", tone: "err" };
  if (mode === "process_isolated_only") return { label: "Process only", tone: "warn" };
  if (mode === "configurable") return { label: "Configurable", tone: "warn" };
  if (mode === "full_access") return { label: "Full access", tone: "err" };
  if (mode === "in_process") return { label: "No sandbox", tone: "muted" };
  return { label: "Unknown", tone: "muted" };
}
function badgeStyle(tone) {
  if (tone === "ok") return { background: "#27ae6018", color: "#27ae60", border: "1px solid #27ae6044" };
  if (tone === "warn") return { background: "#f39c1218", color: "#d68910", border: "1px solid #f39c1244" };
  if (tone === "err") return { background: "#e74c3c18", color: "#e74c3c", border: "1px solid #e74c3c44" };
  return { background: "var(--bg)", color: "var(--text-muted)", border: "1px solid var(--border)" };
}
function SandboxBadge({ sandbox }) {
  const visual = sandboxPresentation(sandbox);
  return /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 11, padding: "1px 7px", borderRadius: 4, fontWeight: 600, ...badgeStyle(visual.tone) }, children: visual.label });
}
function SandboxDetail({ sandbox, compact = false }) {
  if (!sandbox) return null;
  const reason = String(sandbox.reason || "").trim();
  const installHint = String(sandbox.install_hint || "").trim();
  const mode = String(sandbox.mode || "").trim().toLowerCase();
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 4 }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(SandboxBadge, { sandbox }),
      sandbox.provider && sandbox.provider !== "none" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 11, color: "var(--text-muted)" }, children: sandbox.provider })
    ] }),
    !compact && reason && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 11, color: "var(--text-muted)", lineHeight: 1.45 }, children: reason }),
    !compact && installHint && (mode === "blocked" || mode === "process_isolated_only") && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 11, color: "var(--text-muted)", lineHeight: 1.45 }, children: installHint })
  ] });
}
function RuntimeSandboxBanner({ runtime }) {
  if (!runtime || runtime.available) return null;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "div",
    {
      style: {
        background: "rgba(243,156,18,.10)",
        border: "1px solid rgba(243,156,18,.28)",
        borderRadius: 10,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 6
      },
      children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontWeight: 700, fontSize: 13 }, children: "Sandbox limited" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(SandboxBadge, { sandbox: { mode: runtime.supported ? "blocked" : "process_isolated_only" } })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }, children: runtime.reason || "Sandbox support is not fully available in this environment." }),
        runtime.install_hint && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }, children: runtime.install_hint })
      ]
    }
  );
}
function _safeJsonParse(value) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}
function _defaultDesktopForm() {
  return {
    action: "list_apps",
    app: "generic",
    access_mode: "sandbox",
    app_name: "",
    office_app: "outlook",
    phone_number: "",
    handle: "",
    message: "",
    document_path: "",
    url: "",
    timeout: 10
  };
}
function _desktopFormFromInputs(inputs) {
  const source = inputs && typeof inputs === "object" ? inputs : {};
  return {
    ..._defaultDesktopForm(),
    action: String(source.action || "list_apps"),
    app: String(source.app || "generic"),
    access_mode: String(source.access_mode || "sandbox"),
    app_name: String(source.app_name || ""),
    office_app: String(source.office_app || "outlook"),
    phone_number: String(source.phone_number || ""),
    handle: String(source.handle || ""),
    message: String(source.message || ""),
    document_path: String(source.document_path || ""),
    url: String(source.url || ""),
    timeout: Number.isFinite(Number(source.timeout)) ? Number(source.timeout) : 10
  };
}
function _desktopInputsFromForm(form) {
  const source = form || _defaultDesktopForm();
  const action = String(source.action || "list_apps");
  const app = String(source.app || "generic");
  const payload = {
    action,
    app,
    access_mode: String(source.access_mode || "sandbox")
  };
  const timeout = Number(source.timeout);
  if (Number.isFinite(timeout) && timeout > 0) payload.timeout = timeout;
  if (action === "open_app") {
    if (app === "generic" && String(source.app_name || "").trim()) payload.app_name = String(source.app_name).trim();
    if (app === "microsoft_365" && String(source.office_app || "").trim()) payload.office_app = String(source.office_app).trim();
  }
  if (action === "open_chat") {
    if (app === "whatsapp" && String(source.phone_number || "").trim()) payload.phone_number = String(source.phone_number).trim();
    if (app === "telegram" && String(source.handle || "").trim()) payload.handle = String(source.handle).trim();
    if (String(source.message || "").trim()) payload.message = String(source.message).trim();
  }
  if (action === "open_document" && String(source.document_path || "").trim()) {
    payload.document_path = String(source.document_path).trim();
  }
  if (action === "open_url" && String(source.url || "").trim()) {
    payload.url = String(source.url).trim();
  }
  return payload;
}
function SkillsPanel() {
  const { state } = useApp();
  const base = state.backendUrl || "http://127.0.0.1:2151";
  const [tab, setTab] = reactExports.useState("all");
  const [data, setData] = reactExports.useState(null);
  const [loading, setLoading] = reactExports.useState(true);
  const [err, setErr] = reactExports.useState(null);
  const [search, setSearch] = reactExports.useState("");
  const [category, setCategory] = reactExports.useState("");
  const [createOpen, setCreateOpen] = reactExports.useState(false);
  const [testSkill, setTestSkill] = reactExports.useState(null);
  const [actionBusy, setActionBusy] = reactExports.useState(null);
  const load = reactExports.useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      if (category) params.set("category", category);
      const r2 = await fetch(`${base}/api/marketplace/skills?${params}`);
      if (!r2.ok) throw new Error(r2.statusText);
      setData(await r2.json());
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [base, search, category]);
  reactExports.useEffect(() => {
    load();
  }, [load]);
  const handleInstall = async (catalogId) => {
    setActionBusy(catalogId);
    try {
      const r2 = await fetch(`${base}/api/marketplace/skills/${catalogId}/install`, { method: "POST" });
      if (!r2.ok) throw new Error((await r2.json()).error || r2.statusText);
      await load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setActionBusy(null);
    }
  };
  const handleUninstall = async (catalogId) => {
    setActionBusy(catalogId);
    try {
      const r2 = await fetch(`${base}/api/marketplace/skills/${catalogId}/uninstall`, { method: "POST" });
      if (!r2.ok) throw new Error((await r2.json()).error || r2.statusText);
      await load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setActionBusy(null);
    }
  };
  const handleDeleteCustom = async (skillId) => {
    if (!confirm("Delete this skill?")) return;
    try {
      const r2 = await fetch(`${base}/api/marketplace/skills/${skillId}/delete`, { method: "POST" });
      if (!r2.ok) throw new Error((await r2.json()).error || r2.statusText);
      await load();
    } catch (e) {
      setErr(e.message);
    }
  };
  const catalog = data?.catalog || [];
  const custom = data?.custom || [];
  const categories = data?.categories || [];
  const installedCount = data?.installed_count ?? 0;
  const sandboxRuntime = data?.sandbox_runtime || null;
  const filteredCatalog = catalog.filter((s) => {
    if (tab === "installed" && !s.is_installed) return false;
    return true;
  });
  const filteredCustom = custom.filter((s) => {
    if (tab === "installed" && !s.is_installed) return false;
    return true;
  });
  const grouped = groupBy(filteredCatalog, "category");
  const catOrder = ["Recommended", "Development", "Research", "Documents", "Communication", "Data"];
  const sortedCats = [
    ...catOrder.filter((c) => grouped[c]),
    ...Object.keys(grouped).filter((c) => !catOrder.includes(c)).sort()
  ];
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-topbar", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-topbar-left", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-page-title", children: "Skills" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-page-sub", children: "Make Kendr work your way" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-topbar-actions", children: [
        installedCount > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pp-badge pp-badge--ok", children: [
          installedCount,
          " installed"
        ] }),
        sandboxRuntime && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `pp-badge ${sandboxRuntime.available ? "pp-badge--ok" : "pp-badge--warn"}`, children: sandboxRuntime.available ? "Sandbox ready" : "Sandbox limited" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", onClick: load, children: "↺ Refresh" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "pp-btn pp-btn--primary",
            onClick: () => setCreateOpen(true),
            style: { background: "var(--accent)", color: "#fff", border: "none", padding: "5px 14px", borderRadius: 6, cursor: "pointer", fontWeight: 600 },
            children: "+ Create"
          }
        )
      ] })
    ] }),
    err && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-error-banner", children: [
      "⚠ ",
      err,
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: () => setErr(null), children: "✕" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(RuntimeSandboxBanner, { runtime: sandboxRuntime }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-filters", style: { gap: 8 }, children: [
      [["all", "All Skills"], ["installed", "Installed"]].map(([val, label]) => /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: `pp-tab ${tab === val ? "active" : ""}`,
          style: { padding: "5px 14px", borderBottom: "none", borderRadius: 6, border: `1px solid ${tab === val ? "var(--accent)" : "var(--border)"}`, fontWeight: tab === val ? 600 : 400 },
          onClick: () => setTab(val),
          children: label
        },
        val
      )),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "input",
        {
          className: "pp-search",
          placeholder: "Search skills…",
          value: search,
          onChange: (e) => setSearch(e.target.value),
          style: { flex: 1 }
        }
      ),
      categories.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs(
        "select",
        {
          value: category,
          onChange: (e) => setCategory(e.target.value),
          style: { background: "var(--bg-secondary)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 6, padding: "4px 8px", fontSize: 13 },
          children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "", children: "All Categories" }),
            categories.map((c) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: c, children: c }, c))
          ]
        }
      )
    ] }),
    loading ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-loading", children: "Loading skills…" }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-skills-body", children: [
      filteredCustom.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx(SkillSection, { title: "Personal", emoji: "✨", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }, children: filteredCustom.map((skill) => /* @__PURE__ */ jsxRuntimeExports.jsx(
        CustomSkillCard,
        {
          skill,
          onTest: () => setTestSkill(skill),
          onDelete: () => handleDeleteCustom(skill.skill_id)
        },
        skill.skill_id
      )) }) }),
      sortedCats.length === 0 && filteredCustom.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-empty", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-icon", children: "⚡" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-title", children: "No skills found" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-sub", children: "Try a different search or create your own skill." })
      ] }) : sortedCats.map((cat) => /* @__PURE__ */ jsxRuntimeExports.jsx(SkillSection, { title: cat, emoji: CAT_EMOJI[cat] || "🔧", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }, children: grouped[cat].map((skill) => /* @__PURE__ */ jsxRuntimeExports.jsx(
        CatalogSkillCard,
        {
          skill,
          busy: actionBusy === skill.id,
          onInstall: () => handleInstall(skill.id),
          onUninstall: () => handleUninstall(skill.id),
          onTest: skill.is_installed && skill.skill_id ? () => setTestSkill({ ...skill, skill_id: skill.skill_id }) : null
        },
        skill.id
      )) }) }, cat))
    ] }),
    createOpen && /* @__PURE__ */ jsxRuntimeExports.jsx(
      CreateSkillModal,
      {
        base,
        onClose: () => setCreateOpen(false),
        onCreated: () => {
          setCreateOpen(false);
          load();
        }
      }
    ),
    testSkill && /* @__PURE__ */ jsxRuntimeExports.jsx(
      TestSkillModal,
      {
        base,
        skill: testSkill,
        onClose: () => setTestSkill(null)
      }
    )
  ] });
}
const CAT_EMOJI = {
  Recommended: "⭐",
  Development: "💻",
  Research: "🔬",
  Documents: "📄",
  Communication: "💬",
  Data: "📊",
  Custom: "✨"
};
function SkillSection({ title, emoji, children }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-cat-section", style: { marginBottom: 24 }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-cat-header", style: { marginBottom: 12 }, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pp-cat-name", children: [
      emoji,
      " ",
      title
    ] }) }),
    children
  ] });
}
function CatalogSkillCard({ skill, busy, onInstall, onUninstall, onTest }) {
  const installed = skill.is_installed;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "div",
    {
      style: {
        background: "var(--bg-secondary)",
        border: `1px solid ${installed ? "var(--accent)" : "var(--border)"}`,
        borderRadius: 10,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        opacity: busy ? 0.7 : 1,
        transition: "border-color 0.2s"
      },
      children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "flex-start", gap: 10 }, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 26, lineHeight: 1 }, children: skill.icon || "🔧" }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { flex: 1, minWidth: 0 }, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontWeight: 600, fontSize: 14, color: "var(--text)", marginBottom: 2 }, children: skill.name }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.4 }, children: skill.description })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { flexShrink: 0 }, children: installed ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end" }, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 11, color: "var(--accent)", fontWeight: 600, display: "flex", alignItems: "center", gap: 3 }, children: "✓ Installed" }),
            onTest && /* @__PURE__ */ jsxRuntimeExports.jsx(
              "button",
              {
                onClick: onTest,
                style: { fontSize: 11, padding: "2px 8px", background: "transparent", border: "1px solid var(--border)", borderRadius: 4, color: "var(--text-muted)", cursor: "pointer" },
                children: "Test"
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "button",
              {
                onClick: onUninstall,
                disabled: busy,
                style: { fontSize: 11, padding: "2px 8px", background: "transparent", border: "1px solid var(--border)", borderRadius: 4, color: "var(--text-muted)", cursor: "pointer" },
                children: busy ? "…" : "Remove"
              }
            )
          ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              onClick: onInstall,
              disabled: busy,
              style: {
                width: 28,
                height: 28,
                borderRadius: "50%",
                background: "var(--bg)",
                border: "1px solid var(--border)",
                fontSize: 18,
                lineHeight: "28px",
                textAlign: "center",
                cursor: busy ? "not-allowed" : "pointer",
                color: "var(--text)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center"
              },
              title: "Install skill",
              children: busy ? "…" : "+"
            }
          ) })
        ] }),
        skill.tags?.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "flex", flexWrap: "wrap", gap: 4 }, children: skill.tags.slice(0, 4).map((t2, i) => /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-intent-chip", style: { fontSize: 11 }, children: t2 }, i)) }),
        skill.requires_config?.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { fontSize: 11, color: "var(--warn, #e6a700)", display: "flex", alignItems: "center", gap: 4 }, children: [
          "⚙ Requires: ",
          skill.requires_config.join(", ")
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(SandboxDetail, { sandbox: skill.sandbox, compact: true })
      ]
    }
  );
}
function CustomSkillCard({ skill, onTest, onDelete }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "div",
    {
      style: {
        background: "var(--bg-secondary)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8
      },
      children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "flex-start", gap: 10 }, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 26, lineHeight: 1 }, children: skill.icon || "⚡" }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { flex: 1, minWidth: 0 }, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontWeight: 600, fontSize: 14, color: "var(--text)", marginBottom: 2 }, children: skill.name }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.4 }, children: skill.description || "No description." })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end", flexShrink: 0 }, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 11, padding: "2px 7px", background: "var(--bg)", borderRadius: 4, border: "1px solid var(--border)", color: "var(--text-muted)" }, children: skill.skill_type }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "button",
              {
                onClick: onTest,
                style: { fontSize: 11, padding: "2px 8px", background: "transparent", border: "1px solid var(--border)", borderRadius: 4, color: "var(--text-muted)", cursor: "pointer" },
                children: "Test"
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "button",
              {
                onClick: onDelete,
                style: { fontSize: 11, padding: "2px 8px", background: "transparent", border: "1px solid #c0392b44", borderRadius: 4, color: "#e74c3c", cursor: "pointer" },
                children: "Delete"
              }
            )
          ] })
        ] }),
        skill.tags?.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "flex", flexWrap: "wrap", gap: 4 }, children: skill.tags.slice(0, 4).map((t2, i) => /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-intent-chip", style: { fontSize: 11 }, children: t2 }, i)) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(SandboxDetail, { sandbox: skill.sandbox, compact: true })
      ]
    }
  );
}
const STARTER_PYTHON = `# Available variables:
#   inputs (dict)  — the inputs passed to this skill
#   output         — set this to your result
#
# Example:
query = inputs.get('query', '')
output = f"Processed: {query.upper()}"
`;
const STARTER_PROMPT = `You are a helpful assistant.

User query: {query}

Respond with a concise, accurate answer.
`;
function CreateSkillModal({ base, onClose, onCreated }) {
  const [name, setName] = reactExports.useState("");
  const [desc, setDesc] = reactExports.useState("");
  const [category, setCategory] = reactExports.useState("Custom");
  const [icon, setIcon] = reactExports.useState("⚡");
  const [type, setType] = reactExports.useState("python");
  const [code, setCode] = reactExports.useState(STARTER_PYTHON);
  const [tags, setTags] = reactExports.useState("");
  const [err, setErr] = reactExports.useState(null);
  const [busy, setBusy] = reactExports.useState(false);
  reactExports.useEffect(() => {
    setCode(type === "python" ? STARTER_PYTHON : STARTER_PROMPT);
  }, [type]);
  const submit = async () => {
    if (!name.trim()) {
      setErr("Name is required.");
      return;
    }
    if (!code.trim()) {
      setErr("Code / prompt is required.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const r2 = await fetch(`${base}/api/marketplace/skills/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          description: desc.trim(),
          category: category.trim() || "Custom",
          icon: icon.trim() || "⚡",
          skill_type: type,
          code,
          tags: tags.split(",").map((t2) => t2.trim()).filter(Boolean)
        })
      });
      const data = await r2.json();
      if (!r2.ok || !data.ok) throw new Error(data.error || r2.statusText);
      onCreated();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx(ModalOverlay, { onClose, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { width: 580, maxHeight: "90vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 14 }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontWeight: 700, fontSize: 16, marginBottom: 4 }, children: "Create Skill" }),
    err && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { color: "#e74c3c", fontSize: 13, background: "#e74c3c18", padding: "6px 10px", borderRadius: 6 }, children: [
      "⚠ ",
      err
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Name *", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { value: name, onChange: (e) => setName(e.target.value), placeholder: "My Skill", className: "modal-input" }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Icon", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { value: icon, onChange: (e) => setIcon(e.target.value), placeholder: "⚡", className: "modal-input", style: { width: 60 } }) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Description", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { value: desc, onChange: (e) => setDesc(e.target.value), placeholder: "What does this skill do?", className: "modal-input" }) }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Category", children: /* @__PURE__ */ jsxRuntimeExports.jsx("select", { value: category, onChange: (e) => setCategory(e.target.value), className: "modal-input", children: ["Custom", "Development", "Research", "Documents", "Communication", "Data"].map((c) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: c, children: c }, c)) }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Tags (comma-separated)", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { value: tags, onChange: (e) => setTags(e.target.value), placeholder: "search, data, api", className: "modal-input" }) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Skill Type", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "flex", gap: 8 }, children: [["python", "🐍 Python Function"], ["prompt", "💬 Prompt Template"]].map(([val, label]) => /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        onClick: () => setType(val),
        style: {
          flex: 1,
          padding: "8px 12px",
          borderRadius: 8,
          cursor: "pointer",
          border: `1px solid ${type === val ? "var(--accent)" : "var(--border)"}`,
          background: type === val ? "var(--accent)18" : "var(--bg)",
          color: "var(--text)",
          fontWeight: type === val ? 600 : 400,
          fontSize: 13
        },
        children: label
      },
      val
    )) }) }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs(FormField, { label: type === "python" ? "Python Code" : "Prompt Template", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }, children: type === "python" ? 'Set "output" variable to the result. Access inputs via inputs["key"].' : "Use {variable} placeholders for inputs. Sent to the LLM." }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "textarea",
        {
          value: code,
          onChange: (e) => setCode(e.target.value),
          rows: 12,
          className: "modal-input",
          style: { fontFamily: "monospace", fontSize: 12, resize: "vertical", minHeight: 200 }
        }
      )
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", onClick: onClose, disabled: busy, children: "Cancel" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          onClick: submit,
          disabled: busy,
          style: { padding: "7px 18px", background: "var(--accent)", color: "#fff", border: "none", borderRadius: 6, cursor: busy ? "not-allowed" : "pointer", fontWeight: 600 },
          children: busy ? "Creating…" : "Create Skill"
        }
      )
    ] })
  ] }) });
}
function TestSkillModal({ base, skill, onClose }) {
  const skillId = skill.skill_id || skill.id;
  const isDesktopAutomationSkill = String(skill?.catalog_id || skill?.slug || "").trim() === "desktop-automation";
  const approvalSessionIdRef = reactExports.useRef(`skill-test-${String(skillId || "skill").replace(/[^a-z0-9_-]+/ig, "-")}-${Date.now().toString(36)}`);
  const approvalSessionId = approvalSessionIdRef.current;
  const [inputJson, setInputJson] = reactExports.useState(() => {
    try {
      const schema = skill.input_schema || {};
      const ex = skill.example_input || {};
      if (Object.keys(ex).length > 0) return JSON.stringify(ex, null, 2);
      const props = schema.properties || {};
      const demo = {};
      for (const [k2, v2] of Object.entries(props)) {
        demo[k2] = v2.default ?? (v2.type === "string" ? "" : v2.type === "integer" ? 0 : null);
      }
      return JSON.stringify(demo, null, 2);
    } catch {
      return "{}";
    }
  });
  const [result, setResult] = reactExports.useState(null);
  const [busy, setBusy] = reactExports.useState(false);
  const [err, setErr] = reactExports.useState(null);
  const [approvalRequest, setApprovalRequest] = reactExports.useState(null);
  const [approvalNote, setApprovalNote] = reactExports.useState("");
  const [approvalBusy, setApprovalBusy] = reactExports.useState("");
  const [approvalErr, setApprovalErr] = reactExports.useState(null);
  const [grants, setGrants] = reactExports.useState([]);
  const [revokeBusy, setRevokeBusy] = reactExports.useState("");
  const [desktopForm, setDesktopForm] = reactExports.useState(() => {
    const parsed = _safeJsonParse(inputJson);
    return _desktopFormFromInputs(parsed || {});
  });
  const loadApprovals = reactExports.useCallback(async () => {
    try {
      const r2 = await fetch(`${base}/api/marketplace/skills/${skillId}/approvals?status=active`);
      const data = await r2.json().catch(() => ({}));
      if (!r2.ok) throw new Error(data.error || r2.statusText);
      setGrants(Array.isArray(data.items) ? data.items : []);
    } catch (_2) {
    }
  }, [base, skillId]);
  reactExports.useEffect(() => {
    loadApprovals();
  }, [loadApprovals]);
  reactExports.useEffect(() => {
    if (!isDesktopAutomationSkill) return;
    const parsed = _safeJsonParse(inputJson);
    if (!parsed || typeof parsed !== "object") return;
    setDesktopForm(_desktopFormFromInputs(parsed));
  }, [inputJson, isDesktopAutomationSkill]);
  const setDesktopField = reactExports.useCallback((field, value) => {
    setDesktopForm((prev) => {
      const next = { ...prev, [field]: value };
      setInputJson(JSON.stringify(_desktopInputsFromForm(next), null, 2));
      return next;
    });
  }, []);
  const run = reactExports.useCallback(async () => {
    setBusy(true);
    setErr(null);
    setApprovalErr(null);
    setResult(null);
    try {
      let inputs;
      try {
        inputs = JSON.parse(inputJson);
      } catch {
        throw new Error("Invalid JSON in inputs");
      }
      const r2 = await fetch(`${base}/api/marketplace/skills/${skillId}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inputs, session_id: approvalSessionId })
      });
      const data = await r2.json().catch(() => ({}));
      if (r2.status === 409 || data?.error_type === "approval_required") {
        setApprovalRequest(data);
        setResult(data);
        await loadApprovals();
        return;
      }
      if (!r2.ok) throw new Error(data.error || data.detail || r2.statusText);
      setApprovalRequest(null);
      setResult(data);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
      loadApprovals();
    }
  }, [approvalSessionId, base, inputJson, loadApprovals, skillId]);
  const approve = reactExports.useCallback(async (scope) => {
    setApprovalBusy(scope);
    setApprovalErr(null);
    try {
      const r2 = await fetch(`${base}/api/marketplace/skills/${skillId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope,
          note: approvalNote.trim() || `Approved ${skill.name || skill.slug || skillId} from the desktop skills panel (${scope}).`,
          session_id: approvalSessionId
        })
      });
      const data = await r2.json().catch(() => ({}));
      if (!r2.ok || !data.ok) throw new Error(data.error || data.detail || r2.statusText);
      setApprovalRequest(null);
      await loadApprovals();
      await run();
    } catch (e) {
      setApprovalErr(e.message);
    } finally {
      setApprovalBusy("");
    }
  }, [approvalNote, approvalSessionId, base, loadApprovals, run, skill.name, skill.slug, skillId]);
  const revokeGrant = reactExports.useCallback(async (grantId) => {
    setRevokeBusy(grantId);
    setApprovalErr(null);
    try {
      const r2 = await fetch(`${base}/api/marketplace/skills/${skillId}/revoke-approval`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grant_id: grantId })
      });
      const data = await r2.json().catch(() => ({}));
      if (!r2.ok || !data.ok) throw new Error(data.error || data.detail || r2.statusText);
      await loadApprovals();
    } catch (e) {
      setApprovalErr(e.message);
    } finally {
      setRevokeBusy("");
    }
  }, [base, loadApprovals, skillId]);
  const approvalSections = Array.isArray(approvalRequest?.approval_request?.sections) ? approvalRequest.approval_request.sections : [];
  const suggestedScopes = Array.isArray(approvalRequest?.approval_request?.metadata?.suggested_scopes) ? approvalRequest.approval_request.metadata.suggested_scopes : ["once", "session", "always"];
  const isApprovalPending = approvalRequest?.error_type === "approval_required";
  const activeGrants = grants.filter((grant) => String(grant.status || "").toLowerCase() === "active");
  const effectiveSandbox = result?.sandbox || skill?.sandbox || null;
  const desktopAutomation = skill?.desktop_automation || null;
  const desktopApps = Array.isArray(desktopAutomation?.supported_apps) ? desktopAutomation.supported_apps : [];
  return /* @__PURE__ */ jsxRuntimeExports.jsx(ModalOverlay, { onClose, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { width: 560, maxHeight: "85vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 14 }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { fontWeight: 700, fontSize: 16 }, children: [
      skill.icon || "⚡",
      " Test: ",
      skill.name
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 13, color: "var(--text-muted)" }, children: skill.description }),
    err && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { color: "#e74c3c", fontSize: 13 }, children: [
      "⚠ ",
      err
    ] }),
    approvalErr && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { color: "#e74c3c", fontSize: 13 }, children: [
      "⚠ ",
      approvalErr
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pp-badge pp-badge--muted", children: [
        "Session ",
        approvalSessionId.slice(-10)
      ] }),
      activeGrants.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pp-badge pp-badge--warn", children: [
        activeGrants.length,
        " active grant",
        activeGrants.length === 1 ? "" : "s"
      ] })
    ] }),
    desktopAutomation && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 8, background: "rgba(52,152,219,.08)", border: "1px solid rgba(52,152,219,.22)", borderRadius: 10, padding: 12 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontWeight: 600, fontSize: 13 }, children: "Desktop automation modes" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }, children: desktopAutomation.sandbox_notice }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }, children: desktopAutomation.full_access_warning }),
      Array.isArray(desktopAutomation.supported_apps) && desktopAutomation.supported_apps.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "flex", flexWrap: "wrap", gap: 6 }, children: desktopAutomation.supported_apps.map((app) => /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-badge pp-badge--info", children: app.name }, app.id)) })
    ] }),
    effectiveSandbox && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 8, background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 10, padding: 12 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontWeight: 600, fontSize: 13 }, children: "Execution boundary" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(SandboxDetail, { sandbox: effectiveSandbox })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Inputs (JSON)", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      "textarea",
      {
        value: inputJson,
        onChange: (e) => {
          const next = e.target.value;
          setInputJson(next);
          if (isDesktopAutomationSkill) {
            const parsed = _safeJsonParse(next);
            if (parsed && typeof parsed === "object") setDesktopForm(_desktopFormFromInputs(parsed));
          }
        },
        rows: 6,
        className: "modal-input",
        style: { fontFamily: "monospace", fontSize: 12, resize: "vertical" }
      }
    ) }),
    isDesktopAutomationSkill && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Access mode", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "modal-input", value: desktopForm.access_mode, onChange: (e) => setDesktopField("access_mode", e.target.value), children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "sandbox", children: "sandbox (preview only)" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "full_access", children: "full_access (native dispatch)" })
      ] }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Action", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "modal-input", value: desktopForm.action, onChange: (e) => setDesktopField("action", e.target.value), children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "list_apps", children: "list_apps" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "open_app", children: "open_app" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "open_chat", children: "open_chat" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "open_document", children: "open_document" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "open_url", children: "open_url" })
      ] }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "App", children: /* @__PURE__ */ jsxRuntimeExports.jsx("select", { className: "modal-input", value: desktopForm.app, onChange: (e) => setDesktopField("app", e.target.value), children: (desktopApps.length ? desktopApps : [
        { id: "generic", name: "Generic Native App" },
        { id: "whatsapp", name: "WhatsApp" },
        { id: "telegram", name: "Telegram" },
        { id: "microsoft_365", name: "Microsoft 365" }
      ]).map((app) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: app.id, children: app.id }, app.id)) }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Timeout (s)", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        "input",
        {
          className: "modal-input",
          type: "number",
          min: 1,
          value: desktopForm.timeout,
          onChange: (e) => setDesktopField("timeout", Number(e.target.value || 10))
        }
      ) }),
      desktopForm.action === "open_app" && desktopForm.app === "generic" && /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "App name", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "modal-input", value: desktopForm.app_name, onChange: (e) => setDesktopField("app_name", e.target.value), placeholder: "Telegram Desktop" }) }),
      desktopForm.action === "open_app" && desktopForm.app === "microsoft_365" && /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Office app", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "modal-input", value: desktopForm.office_app, onChange: (e) => setDesktopField("office_app", e.target.value), children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "outlook", children: "outlook" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "word", children: "word" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "excel", children: "excel" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "powerpoint", children: "powerpoint" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "teams", children: "teams" })
      ] }) }),
      desktopForm.action === "open_chat" && desktopForm.app === "whatsapp" && /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Phone number", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "modal-input", value: desktopForm.phone_number, onChange: (e) => setDesktopField("phone_number", e.target.value), placeholder: "+14155550123" }) }),
      desktopForm.action === "open_chat" && desktopForm.app === "telegram" && /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Telegram handle", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "modal-input", value: desktopForm.handle, onChange: (e) => setDesktopField("handle", e.target.value), placeholder: "OpenAI" }) }),
      desktopForm.action === "open_chat" && /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Message", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "modal-input", value: desktopForm.message, onChange: (e) => setDesktopField("message", e.target.value), placeholder: "Optional message draft" }) }),
      desktopForm.action === "open_document" && /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Document path", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "modal-input", value: desktopForm.document_path, onChange: (e) => setDesktopField("document_path", e.target.value), placeholder: "/path/to/file.docx" }) }),
      desktopForm.action === "open_url" && /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "URL", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "modal-input", value: desktopForm.url, onChange: (e) => setDesktopField("url", e.target.value), placeholder: "https://example.com" }) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        onClick: run,
        disabled: busy,
        style: { alignSelf: "flex-end", padding: "7px 18px", background: "var(--accent)", color: "#fff", border: "none", borderRadius: 6, cursor: busy ? "not-allowed" : "pointer", fontWeight: 600 },
        children: busy ? "⏳ Running…" : "▶ Run Test"
      }
    ),
    isApprovalPending && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 10, background: "rgba(255,179,71,.08)", border: "1px solid rgba(255,179,71,.3)", borderRadius: 10, padding: 14 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 8 }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontWeight: 700, fontSize: 13 }, children: "Permission required" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-badge pp-badge--warn", children: "approval required" })
      ] }),
      approvalRequest?.approval_request?.summary && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.55 }, children: approvalRequest.approval_request.summary }),
      approvalSections.map((section, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 6 }, children: [
        section.title && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: ".08em" }, children: section.title }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("ul", { style: { margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4, color: "var(--text)" }, children: (section.items || []).map((item, itemIndex) => /* @__PURE__ */ jsxRuntimeExports.jsx("li", { style: { fontSize: 12, lineHeight: 1.5 }, children: item }, `${index2}-${itemIndex}`)) })
      ] }, `${section.title || "section"}-${index2}`)),
      approvalRequest?.approval_request?.help_text && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }, children: approvalRequest.approval_request.help_text }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(FormField, { label: "Approval note", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        "textarea",
        {
          value: approvalNote,
          onChange: (e) => setApprovalNote(e.target.value),
          rows: 2,
          className: "modal-input",
          placeholder: "Optional note for the audit log"
        }
      ) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "flex", gap: 8, flexWrap: "wrap" }, children: suggestedScopes.map((scope) => /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          onClick: () => approve(scope),
          disabled: !!approvalBusy,
          className: "pp-btn pp-btn--primary",
          children: approvalBusy === scope ? "Approving…" : scope === "session" ? "Allow this session" : scope === "always" ? "Always allow" : "Allow once"
        },
        scope
      )) })
    ] }),
    activeGrants.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 8 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontWeight: 600, fontSize: 13 }, children: "Active grants" }),
      activeGrants.map((grant) => {
        const isCurrentSession = grant.session_id && grant.session_id === approvalSessionId;
        return /* @__PURE__ */ jsxRuntimeExports.jsxs(
          "div",
          {
            style: {
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: "10px 12px",
              background: "var(--bg)"
            },
            children: [
              /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }, children: [
                /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }, children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-badge pp-badge--ok", children: grant.scope }),
                  isCurrentSession && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-badge pp-badge--info", children: "current session" }),
                  /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 11, color: "var(--text-muted)" }, children: grant.actor || "user" })
                ] }),
                grant.note && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.45 }, children: grant.note })
              ] }),
              /* @__PURE__ */ jsxRuntimeExports.jsx(
                "button",
                {
                  onClick: () => revokeGrant(grant.grant_id),
                  disabled: revokeBusy === grant.grant_id,
                  className: "pp-btn pp-btn--ghost",
                  children: revokeBusy === grant.grant_id ? "Revoking…" : "Revoke"
                }
              )
            ]
          },
          grant.grant_id
        );
      })
    ] }),
    result && !isApprovalPending && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 8 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 8 }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontWeight: 600, fontSize: 13 }, children: "Result" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: {
          fontSize: 11,
          padding: "1px 7px",
          borderRadius: 4,
          background: result.success ? "#27ae6018" : "#e74c3c18",
          color: result.success ? "#27ae60" : "#e74c3c",
          border: `1px solid ${result.success ? "#27ae6044" : "#e74c3c44"}`
        }, children: result.success ? "✓ success" : "✕ failed" }),
        typeof result.output?.preview_only === "boolean" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `pp-badge ${result.output.preview_only ? "pp-badge--warn" : "pp-badge--ok"}`, children: result.output.preview_only ? "preview only" : "dispatched" })
      ] }),
      result.stdout && /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { style: { background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6, padding: 10, fontSize: 12, overflowX: "auto", maxHeight: 200, margin: 0 }, children: result.stdout }),
      result.error && /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { style: { background: "#e74c3c0a", border: "1px solid #e74c3c44", borderRadius: 6, padding: 10, fontSize: 12, color: "#e74c3c", overflowX: "auto", maxHeight: 150, margin: 0 }, children: result.error }),
      result.output && typeof result.output === "object" && /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { style: { background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6, padding: 10, fontSize: 12, overflowX: "auto", maxHeight: 220, margin: 0 }, children: JSON.stringify(result.output, null, 2) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "flex", justifyContent: "flex-end" }, children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", onClick: onClose, children: "Close" }) })
  ] }) });
}
function ModalOverlay({ onClose, children }) {
  const overlayRef = reactExports.useRef(null);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "div",
    {
      ref: overlayRef,
      onClick: (e) => {
        if (e.target === overlayRef.current) onClose();
      },
      style: {
        position: "fixed",
        inset: 0,
        zIndex: 1e3,
        background: "rgba(0,0,0,0.55)",
        backdropFilter: "blur(3px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center"
      },
      children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: {
        background: "var(--bg-secondary, #1e1e2e)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: 24,
        boxShadow: "0 24px 48px #0008"
      }, children })
    }
  );
}
function FormField({ label, children }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 4 }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("label", { style: { fontSize: 12, fontWeight: 600, color: "var(--text-muted)" }, children: label }),
    children
  ] });
}
const FILE_ICONS$1 = {
  js: "⚡",
  jsx: "⚛",
  ts: "🔷",
  tsx: "⚛",
  py: "🐍",
  json: "{}",
  md: "📝",
  html: "🌐",
  css: "🎨",
  yml: "⚙",
  yaml: "⚙",
  sh: "💻",
  rs: "⚙",
  go: "🐹",
  java: "☕",
  sql: "🗄",
  txt: "📄",
  env: "🔐",
  toml: "⚙",
  xml: "📋",
  png: "🖼",
  jpg: "🖼",
  svg: "🖼",
  pdf: "📑",
  zip: "📦",
  lock: "🔒",
  gitignore: "⊘"
};
function TreeNode({ node, depth = 0, onContextMenu }) {
  const [open, setOpen] = reactExports.useState(depth < 2);
  const [children, setChildren] = reactExports.useState(null);
  const { openFile } = useApp();
  const api = window.kendrAPI;
  const loadChildren = reactExports.useCallback(async () => {
    if (!node.isDirectory) return;
    const entries = await api?.fs.readDir(node.path);
    if (Array.isArray(entries)) setChildren(entries);
  }, [node]);
  reactExports.useEffect(() => {
    if (open && node.isDirectory && children === null) loadChildren();
  }, [open, node.isDirectory]);
  const toggle = () => {
    if (node.isDirectory) setOpen((o) => !o);
    else openFile(node.path);
  };
  const ext = node.name.split(".").pop()?.toLowerCase() || "";
  const icon = node.isDirectory ? open ? "📂" : "📁" : FILE_ICONS$1[ext] || "📄";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: "tree-node",
        style: { paddingLeft: `${depth * 12 + 8}px` },
        onClick: toggle,
        onContextMenu: (e) => onContextMenu(e, node),
        title: node.path,
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "tree-icon", children: icon }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "tree-name", children: node.name })
        ]
      }
    ),
    node.isDirectory && open && children && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: children.map((child) => /* @__PURE__ */ jsxRuntimeExports.jsx(TreeNode, { node: child, depth: depth + 1, onContextMenu }, child.path)) })
  ] });
}
function FileExplorer() {
  const { state, dispatch } = useApp();
  const [rootEntries, setRootEntries] = reactExports.useState([]);
  const [contextMenu, setContextMenu] = reactExports.useState(null);
  const [renaming, setRenaming] = reactExports.useState(null);
  const [newFileName, setNewFileName] = reactExports.useState("");
  const api = window.kendrAPI;
  const loadRoot = reactExports.useCallback(async () => {
    if (!state.projectRoot) return;
    const entries = await api?.fs.readDir(state.projectRoot);
    if (Array.isArray(entries)) setRootEntries(entries);
  }, [state.projectRoot]);
  reactExports.useEffect(() => {
    loadRoot();
  }, [state.projectRoot]);
  const openFolder = async () => {
    const dir = await api?.dialog.openDirectory();
    if (dir) {
      dispatch({ type: "SET_PROJECT_ROOT", root: dir });
      await api?.settings.set("projectRoot", dir);
    }
  };
  const handleContextMenu = (e, node) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, node });
  };
  const closeCtx = () => setContextMenu(null);
  const ctxAction = async (action) => {
    const node = contextMenu?.node;
    closeCtx();
    if (!node) return;
    if (action === "open" && !node.isDirectory) {
      const { openFile } = useApp();
    }
    if (action === "rename") {
      setRenaming(node);
      setNewFileName(node.name);
    }
    if (action === "delete") {
      if (confirm(`Delete "${node.name}"?`)) {
        await api?.fs.delete(node.path);
        loadRoot();
      }
    }
    if (action === "new-file") {
      const name = prompt("File name:");
      if (name) {
        const newPath = `${node.isDirectory ? node.path : node.path.split(/[\\/]/).slice(0, -1).join("/")}/${name}`;
        await api?.fs.createFile(newPath.replace(/\//g, require ? "\\" : "/"));
        loadRoot();
      }
    }
    if (action === "new-folder") {
      const name = prompt("Folder name:");
      if (name) {
        const base = node.isDirectory ? node.path : node.path.split(/[\\/]/).slice(0, -1).join("\\");
        await api?.fs.createDir(`${base}\\${name}`);
        loadRoot();
      }
    }
  };
  const confirmRename = async () => {
    if (!renaming || !newFileName.trim()) {
      setRenaming(null);
      return;
    }
    const dir = renaming.path.split(/[\\/]/).slice(0, -1).join("\\");
    const newPath = `${dir}\\${newFileName.trim()}`;
    await api?.fs.rename(renaming.path, newPath);
    setRenaming(null);
    loadRoot();
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "file-explorer", onClick: () => contextMenu && closeCtx(), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "explorer-toolbar", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "icon-btn", title: "Open folder", onClick: openFolder, children: /* @__PURE__ */ jsxRuntimeExports.jsx(FolderOpenIcon, {}) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "icon-btn", title: "Refresh", onClick: loadRoot, children: /* @__PURE__ */ jsxRuntimeExports.jsx(RefreshIcon, {}) }),
      state.projectRoot && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "explorer-root-name", title: state.projectRoot, children: state.projectRoot.split(/[\\/]/).pop() })
    ] }),
    !state.projectRoot ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "explorer-empty", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "btn-primary", onClick: openFolder, children: "Open Folder" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Select a folder to start exploring" })
    ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "tree-root", children: rootEntries.map((entry) => /* @__PURE__ */ jsxRuntimeExports.jsx(TreeNode, { node: entry, depth: 0, onContextMenu: handleContextMenu }, entry.path)) }),
    renaming && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "rename-overlay", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      "input",
      {
        autoFocus: true,
        className: "rename-input",
        value: newFileName,
        onChange: (e) => setNewFileName(e.target.value),
        onKeyDown: (e) => {
          if (e.key === "Enter") confirmRename();
          if (e.key === "Escape") setRenaming(null);
        },
        onBlur: confirmRename
      }
    ) }),
    contextMenu && /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: "context-menu",
        style: { top: contextMenu.y, left: contextMenu.x },
        onClick: (e) => e.stopPropagation(),
        children: [
          !contextMenu.node.isDirectory && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ctx-item", onClick: () => ctxAction("open"), children: "Open" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ctx-item", onClick: () => ctxAction("new-file"), children: "New File" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ctx-item", onClick: () => ctxAction("new-folder"), children: "New Folder" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ctx-divider" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ctx-item", onClick: () => ctxAction("rename"), children: "Rename" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ctx-item ctx-item--danger", onClick: () => ctxAction("delete"), children: "Delete" })
        ]
      }
    )
  ] });
}
function FolderOpenIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" }) });
}
function RefreshIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("polyline", { points: "23 4 23 10 17 10" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("polyline", { points: "1 20 1 14 7 14" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" })
  ] });
}
function _arrayLikeToArray(r2, a) {
  (null == a || a > r2.length) && (a = r2.length);
  for (var e = 0, n2 = Array(a); e < a; e++) n2[e] = r2[e];
  return n2;
}
function _arrayWithHoles(r2) {
  if (Array.isArray(r2)) return r2;
}
function _defineProperty$1(e, r2, t2) {
  return (r2 = _toPropertyKey(r2)) in e ? Object.defineProperty(e, r2, {
    value: t2,
    enumerable: true,
    configurable: true,
    writable: true
  }) : e[r2] = t2, e;
}
function _iterableToArrayLimit(r2, l2) {
  var t2 = null == r2 ? null : "undefined" != typeof Symbol && r2[Symbol.iterator] || r2["@@iterator"];
  if (null != t2) {
    var e, n2, i, u2, a = [], f2 = true, o = false;
    try {
      if (i = (t2 = t2.call(r2)).next, 0 === l2) ;
      else for (; !(f2 = (e = i.call(t2)).done) && (a.push(e.value), a.length !== l2); f2 = true) ;
    } catch (r3) {
      o = true, n2 = r3;
    } finally {
      try {
        if (!f2 && null != t2.return && (u2 = t2.return(), Object(u2) !== u2)) return;
      } finally {
        if (o) throw n2;
      }
    }
    return a;
  }
}
function _nonIterableRest() {
  throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.");
}
function ownKeys$1(e, r2) {
  var t2 = Object.keys(e);
  if (Object.getOwnPropertySymbols) {
    var o = Object.getOwnPropertySymbols(e);
    r2 && (o = o.filter(function(r3) {
      return Object.getOwnPropertyDescriptor(e, r3).enumerable;
    })), t2.push.apply(t2, o);
  }
  return t2;
}
function _objectSpread2$1(e) {
  for (var r2 = 1; r2 < arguments.length; r2++) {
    var t2 = null != arguments[r2] ? arguments[r2] : {};
    r2 % 2 ? ownKeys$1(Object(t2), true).forEach(function(r3) {
      _defineProperty$1(e, r3, t2[r3]);
    }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t2)) : ownKeys$1(Object(t2)).forEach(function(r3) {
      Object.defineProperty(e, r3, Object.getOwnPropertyDescriptor(t2, r3));
    });
  }
  return e;
}
function _objectWithoutProperties(e, t2) {
  if (null == e) return {};
  var o, r2, i = _objectWithoutPropertiesLoose(e, t2);
  if (Object.getOwnPropertySymbols) {
    var n2 = Object.getOwnPropertySymbols(e);
    for (r2 = 0; r2 < n2.length; r2++) o = n2[r2], -1 === t2.indexOf(o) && {}.propertyIsEnumerable.call(e, o) && (i[o] = e[o]);
  }
  return i;
}
function _objectWithoutPropertiesLoose(r2, e) {
  if (null == r2) return {};
  var t2 = {};
  for (var n2 in r2) if ({}.hasOwnProperty.call(r2, n2)) {
    if (-1 !== e.indexOf(n2)) continue;
    t2[n2] = r2[n2];
  }
  return t2;
}
function _slicedToArray(r2, e) {
  return _arrayWithHoles(r2) || _iterableToArrayLimit(r2, e) || _unsupportedIterableToArray(r2, e) || _nonIterableRest();
}
function _toPrimitive(t2, r2) {
  if ("object" != typeof t2 || !t2) return t2;
  var e = t2[Symbol.toPrimitive];
  if (void 0 !== e) {
    var i = e.call(t2, r2);
    if ("object" != typeof i) return i;
    throw new TypeError("@@toPrimitive must return a primitive value.");
  }
  return ("string" === r2 ? String : Number)(t2);
}
function _toPropertyKey(t2) {
  var i = _toPrimitive(t2, "string");
  return "symbol" == typeof i ? i : i + "";
}
function _unsupportedIterableToArray(r2, a) {
  if (r2) {
    if ("string" == typeof r2) return _arrayLikeToArray(r2, a);
    var t2 = {}.toString.call(r2).slice(8, -1);
    return "Object" === t2 && r2.constructor && (t2 = r2.constructor.name), "Map" === t2 || "Set" === t2 ? Array.from(r2) : "Arguments" === t2 || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t2) ? _arrayLikeToArray(r2, a) : void 0;
  }
}
function _defineProperty(obj, key, value) {
  if (key in obj) {
    Object.defineProperty(obj, key, {
      value,
      enumerable: true,
      configurable: true,
      writable: true
    });
  } else {
    obj[key] = value;
  }
  return obj;
}
function ownKeys(object, enumerableOnly) {
  var keys = Object.keys(object);
  if (Object.getOwnPropertySymbols) {
    var symbols = Object.getOwnPropertySymbols(object);
    if (enumerableOnly) symbols = symbols.filter(function(sym) {
      return Object.getOwnPropertyDescriptor(object, sym).enumerable;
    });
    keys.push.apply(keys, symbols);
  }
  return keys;
}
function _objectSpread2(target) {
  for (var i = 1; i < arguments.length; i++) {
    var source = arguments[i] != null ? arguments[i] : {};
    if (i % 2) {
      ownKeys(Object(source), true).forEach(function(key) {
        _defineProperty(target, key, source[key]);
      });
    } else if (Object.getOwnPropertyDescriptors) {
      Object.defineProperties(target, Object.getOwnPropertyDescriptors(source));
    } else {
      ownKeys(Object(source)).forEach(function(key) {
        Object.defineProperty(target, key, Object.getOwnPropertyDescriptor(source, key));
      });
    }
  }
  return target;
}
function compose$1() {
  for (var _len = arguments.length, fns = new Array(_len), _key = 0; _key < _len; _key++) {
    fns[_key] = arguments[_key];
  }
  return function(x2) {
    return fns.reduceRight(function(y2, f2) {
      return f2(y2);
    }, x2);
  };
}
function curry$1(fn) {
  return function curried() {
    var _this = this;
    for (var _len2 = arguments.length, args = new Array(_len2), _key2 = 0; _key2 < _len2; _key2++) {
      args[_key2] = arguments[_key2];
    }
    return args.length >= fn.length ? fn.apply(this, args) : function() {
      for (var _len3 = arguments.length, nextArgs = new Array(_len3), _key3 = 0; _key3 < _len3; _key3++) {
        nextArgs[_key3] = arguments[_key3];
      }
      return curried.apply(_this, [].concat(args, nextArgs));
    };
  };
}
function isObject$1(value) {
  return {}.toString.call(value).includes("Object");
}
function isEmpty(obj) {
  return !Object.keys(obj).length;
}
function isFunction(value) {
  return typeof value === "function";
}
function hasOwnProperty(object, property) {
  return Object.prototype.hasOwnProperty.call(object, property);
}
function validateChanges(initial, changes) {
  if (!isObject$1(changes)) errorHandler$1("changeType");
  if (Object.keys(changes).some(function(field) {
    return !hasOwnProperty(initial, field);
  })) errorHandler$1("changeField");
  return changes;
}
function validateSelector(selector) {
  if (!isFunction(selector)) errorHandler$1("selectorType");
}
function validateHandler(handler) {
  if (!(isFunction(handler) || isObject$1(handler))) errorHandler$1("handlerType");
  if (isObject$1(handler) && Object.values(handler).some(function(_handler) {
    return !isFunction(_handler);
  })) errorHandler$1("handlersType");
}
function validateInitial(initial) {
  if (!initial) errorHandler$1("initialIsRequired");
  if (!isObject$1(initial)) errorHandler$1("initialType");
  if (isEmpty(initial)) errorHandler$1("initialContent");
}
function throwError$1(errorMessages2, type) {
  throw new Error(errorMessages2[type] || errorMessages2["default"]);
}
var errorMessages$1 = {
  initialIsRequired: "initial state is required",
  initialType: "initial state should be an object",
  initialContent: "initial state shouldn't be an empty object",
  handlerType: "handler should be an object or a function",
  handlersType: "all handlers should be a functions",
  selectorType: "selector should be a function",
  changeType: "provided value of changes should be an object",
  changeField: 'it seams you want to change a field in the state which is not specified in the "initial" state',
  "default": "an unknown error accured in `state-local` package"
};
var errorHandler$1 = curry$1(throwError$1)(errorMessages$1);
var validators$1 = {
  changes: validateChanges,
  selector: validateSelector,
  handler: validateHandler,
  initial: validateInitial
};
function create(initial) {
  var handler = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {};
  validators$1.initial(initial);
  validators$1.handler(handler);
  var state = {
    current: initial
  };
  var didUpdate = curry$1(didStateUpdate)(state, handler);
  var update = curry$1(updateState)(state);
  var validate = curry$1(validators$1.changes)(initial);
  var getChanges = curry$1(extractChanges)(state);
  function getState2() {
    var selector = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : function(state2) {
      return state2;
    };
    validators$1.selector(selector);
    return selector(state.current);
  }
  function setState2(causedChanges) {
    compose$1(didUpdate, update, validate, getChanges)(causedChanges);
  }
  return [getState2, setState2];
}
function extractChanges(state, causedChanges) {
  return isFunction(causedChanges) ? causedChanges(state.current) : causedChanges;
}
function updateState(state, changes) {
  state.current = _objectSpread2(_objectSpread2({}, state.current), changes);
  return changes;
}
function didStateUpdate(state, handler, changes) {
  isFunction(handler) ? handler(state.current) : Object.keys(changes).forEach(function(field) {
    var _handler$field;
    return (_handler$field = handler[field]) === null || _handler$field === void 0 ? void 0 : _handler$field.call(handler, state.current[field]);
  });
  return changes;
}
var index = {
  create
};
var config$1 = {
  paths: {
    vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.55.1/min/vs"
  }
};
function curry(fn) {
  return function curried() {
    var _this = this;
    for (var _len = arguments.length, args = new Array(_len), _key = 0; _key < _len; _key++) {
      args[_key] = arguments[_key];
    }
    return args.length >= fn.length ? fn.apply(this, args) : function() {
      for (var _len2 = arguments.length, nextArgs = new Array(_len2), _key2 = 0; _key2 < _len2; _key2++) {
        nextArgs[_key2] = arguments[_key2];
      }
      return curried.apply(_this, [].concat(args, nextArgs));
    };
  };
}
function isObject(value) {
  return {}.toString.call(value).includes("Object");
}
function validateConfig(config2) {
  if (!config2) errorHandler("configIsRequired");
  if (!isObject(config2)) errorHandler("configType");
  if (config2.urls) {
    informAboutDeprecation();
    return {
      paths: {
        vs: config2.urls.monacoBase
      }
    };
  }
  return config2;
}
function informAboutDeprecation() {
  console.warn(errorMessages.deprecation);
}
function throwError(errorMessages2, type) {
  throw new Error(errorMessages2[type] || errorMessages2["default"]);
}
var errorMessages = {
  configIsRequired: "the configuration object is required",
  configType: "the configuration object should be an object",
  "default": "an unknown error accured in `@monaco-editor/loader` package",
  deprecation: "Deprecation warning!\n    You are using deprecated way of configuration.\n\n    Instead of using\n      monaco.config({ urls: { monacoBase: '...' } })\n    use\n      monaco.config({ paths: { vs: '...' } })\n\n    For more please check the link https://github.com/suren-atoyan/monaco-loader#config\n  "
};
var errorHandler = curry(throwError)(errorMessages);
var validators = {
  config: validateConfig
};
var compose = function compose2() {
  for (var _len = arguments.length, fns = new Array(_len), _key = 0; _key < _len; _key++) {
    fns[_key] = arguments[_key];
  }
  return function(x2) {
    return fns.reduceRight(function(y2, f2) {
      return f2(y2);
    }, x2);
  };
};
function merge(target, source) {
  Object.keys(source).forEach(function(key) {
    if (source[key] instanceof Object) {
      if (target[key]) {
        Object.assign(source[key], merge(target[key], source[key]));
      }
    }
  });
  return _objectSpread2$1(_objectSpread2$1({}, target), source);
}
var CANCELATION_MESSAGE = {
  type: "cancelation",
  msg: "operation is manually canceled"
};
function makeCancelable(promise) {
  var hasCanceled_ = false;
  var wrappedPromise = new Promise(function(resolve, reject) {
    promise.then(function(val) {
      return hasCanceled_ ? reject(CANCELATION_MESSAGE) : resolve(val);
    });
    promise["catch"](reject);
  });
  return wrappedPromise.cancel = function() {
    return hasCanceled_ = true;
  }, wrappedPromise;
}
var _excluded = ["monaco"];
var _state$create = index.create({
  config: config$1,
  isInitialized: false,
  resolve: null,
  reject: null,
  monaco: null
}), _state$create2 = _slicedToArray(_state$create, 2), getState = _state$create2[0], setState = _state$create2[1];
function config(globalConfig) {
  var _validators$config = validators.config(globalConfig), monaco = _validators$config.monaco, config2 = _objectWithoutProperties(_validators$config, _excluded);
  setState(function(state2) {
    return {
      config: merge(state2.config, config2),
      monaco
    };
  });
}
function init() {
  var state2 = getState(function(_ref) {
    var monaco = _ref.monaco, isInitialized = _ref.isInitialized, resolve = _ref.resolve;
    return {
      monaco,
      isInitialized,
      resolve
    };
  });
  if (!state2.isInitialized) {
    setState({
      isInitialized: true
    });
    if (state2.monaco) {
      state2.resolve(state2.monaco);
      return makeCancelable(wrapperPromise);
    }
    if (window.monaco && window.monaco.editor) {
      storeMonacoInstance(window.monaco);
      state2.resolve(window.monaco);
      return makeCancelable(wrapperPromise);
    }
    compose(injectScripts, getMonacoLoaderScript)(configureLoader);
  }
  return makeCancelable(wrapperPromise);
}
function injectScripts(script) {
  return document.body.appendChild(script);
}
function createScript(src) {
  var script = document.createElement("script");
  return src && (script.src = src), script;
}
function getMonacoLoaderScript(configureLoader2) {
  var state2 = getState(function(_ref2) {
    var config2 = _ref2.config, reject = _ref2.reject;
    return {
      config: config2,
      reject
    };
  });
  var loaderScript = createScript("".concat(state2.config.paths.vs, "/loader.js"));
  loaderScript.onload = function() {
    return configureLoader2();
  };
  loaderScript.onerror = state2.reject;
  return loaderScript;
}
function configureLoader() {
  var state2 = getState(function(_ref3) {
    var config2 = _ref3.config, resolve = _ref3.resolve, reject = _ref3.reject;
    return {
      config: config2,
      resolve,
      reject
    };
  });
  var require2 = window.require;
  require2.config(state2.config);
  require2(["vs/editor/editor.main"], function(loaded) {
    var monaco = loaded.m || loaded;
    storeMonacoInstance(monaco);
    state2.resolve(monaco);
  }, function(error) {
    state2.reject(error);
  });
}
function storeMonacoInstance(monaco) {
  if (!getState().monaco) {
    setState({
      monaco
    });
  }
}
function __getMonacoInstance() {
  return getState(function(_ref4) {
    var monaco = _ref4.monaco;
    return monaco;
  });
}
var wrapperPromise = new Promise(function(resolve, reject) {
  return setState({
    resolve,
    reject
  });
});
var loader = {
  config,
  init,
  __getMonacoInstance
};
var le = { wrapper: { display: "flex", position: "relative", textAlign: "initial" }, fullWidth: { width: "100%" }, hide: { display: "none" } }, v = le;
var ae = { container: { display: "flex", height: "100%", width: "100%", justifyContent: "center", alignItems: "center" } }, Y = ae;
function Me({ children: e }) {
  return React.createElement("div", { style: Y.container }, e);
}
var Z = Me;
var $ = Z;
function Ee({ width: e, height: r2, isEditorReady: n2, loading: t2, _ref: a, className: m2, wrapperProps: E2 }) {
  return React.createElement("section", { style: { ...v.wrapper, width: e, height: r2 }, ...E2 }, !n2 && React.createElement($, null, t2), React.createElement("div", { ref: a, style: { ...v.fullWidth, ...!n2 && v.hide }, className: m2 }));
}
var ee = Ee;
var H = reactExports.memo(ee);
function Ce(e) {
  reactExports.useEffect(e, []);
}
var k = Ce;
function he(e, r2, n2 = true) {
  let t2 = reactExports.useRef(true);
  reactExports.useEffect(t2.current || !n2 ? () => {
    t2.current = false;
  } : e, r2);
}
var l = he;
function D() {
}
function h(e, r2, n2, t2) {
  return De(e, t2) || be(e, r2, n2, t2);
}
function De(e, r2) {
  return e.editor.getModel(te(e, r2));
}
function be(e, r2, n2, t2) {
  return e.editor.createModel(r2, n2, t2 ? te(e, t2) : void 0);
}
function te(e, r2) {
  return e.Uri.parse(r2);
}
function Oe({ original: e, modified: r2, language: n2, originalLanguage: t2, modifiedLanguage: a, originalModelPath: m2, modifiedModelPath: E2, keepCurrentOriginalModel: g = false, keepCurrentModifiedModel: N2 = false, theme: x2 = "light", loading: P2 = "Loading...", options: y2 = {}, height: V2 = "100%", width: z2 = "100%", className: F2, wrapperProps: j = {}, beforeMount: A2 = D, onMount: q2 = D }) {
  let [M2, O2] = reactExports.useState(false), [T2, s] = reactExports.useState(true), u2 = reactExports.useRef(null), c = reactExports.useRef(null), w2 = reactExports.useRef(null), d = reactExports.useRef(q2), o = reactExports.useRef(A2), b = reactExports.useRef(false);
  k(() => {
    let i = loader.init();
    return i.then((f2) => (c.current = f2) && s(false)).catch((f2) => f2?.type !== "cancelation" && console.error("Monaco initialization: error:", f2)), () => u2.current ? I2() : i.cancel();
  }), l(() => {
    if (u2.current && c.current) {
      let i = u2.current.getOriginalEditor(), f2 = h(c.current, e || "", t2 || n2 || "text", m2 || "");
      f2 !== i.getModel() && i.setModel(f2);
    }
  }, [m2], M2), l(() => {
    if (u2.current && c.current) {
      let i = u2.current.getModifiedEditor(), f2 = h(c.current, r2 || "", a || n2 || "text", E2 || "");
      f2 !== i.getModel() && i.setModel(f2);
    }
  }, [E2], M2), l(() => {
    let i = u2.current.getModifiedEditor();
    i.getOption(c.current.editor.EditorOption.readOnly) ? i.setValue(r2 || "") : r2 !== i.getValue() && (i.executeEdits("", [{ range: i.getModel().getFullModelRange(), text: r2 || "", forceMoveMarkers: true }]), i.pushUndoStop());
  }, [r2], M2), l(() => {
    u2.current?.getModel()?.original.setValue(e || "");
  }, [e], M2), l(() => {
    let { original: i, modified: f2 } = u2.current.getModel();
    c.current.editor.setModelLanguage(i, t2 || n2 || "text"), c.current.editor.setModelLanguage(f2, a || n2 || "text");
  }, [n2, t2, a], M2), l(() => {
    c.current?.editor.setTheme(x2);
  }, [x2], M2), l(() => {
    u2.current?.updateOptions(y2);
  }, [y2], M2);
  let L2 = reactExports.useCallback(() => {
    if (!c.current) return;
    o.current(c.current);
    let i = h(c.current, e || "", t2 || n2 || "text", m2 || ""), f2 = h(c.current, r2 || "", a || n2 || "text", E2 || "");
    u2.current?.setModel({ original: i, modified: f2 });
  }, [n2, r2, a, e, t2, m2, E2]), U2 = reactExports.useCallback(() => {
    !b.current && w2.current && (u2.current = c.current.editor.createDiffEditor(w2.current, { automaticLayout: true, ...y2 }), L2(), c.current?.editor.setTheme(x2), O2(true), b.current = true);
  }, [y2, x2, L2]);
  reactExports.useEffect(() => {
    M2 && d.current(u2.current, c.current);
  }, [M2]), reactExports.useEffect(() => {
    !T2 && !M2 && U2();
  }, [T2, M2, U2]);
  function I2() {
    let i = u2.current?.getModel();
    g || i?.original?.dispose(), N2 || i?.modified?.dispose(), u2.current?.dispose();
  }
  return React.createElement(H, { width: z2, height: V2, isEditorReady: M2, loading: P2, _ref: w2, className: F2, wrapperProps: j });
}
var ie = Oe;
var we = reactExports.memo(ie);
function He(e) {
  let r2 = reactExports.useRef();
  return reactExports.useEffect(() => {
    r2.current = e;
  }, [e]), r2.current;
}
var se = He;
var _ = /* @__PURE__ */ new Map();
function Ve({ defaultValue: e, defaultLanguage: r2, defaultPath: n2, value: t2, language: a, path: m2, theme: E2 = "light", line: g, loading: N2 = "Loading...", options: x2 = {}, overrideServices: P2 = {}, saveViewState: y2 = true, keepCurrentModel: V2 = false, width: z2 = "100%", height: F2 = "100%", className: j, wrapperProps: A2 = {}, beforeMount: q2 = D, onMount: M2 = D, onChange: O2, onValidate: T2 = D }) {
  let [s, u2] = reactExports.useState(false), [c, w2] = reactExports.useState(true), d = reactExports.useRef(null), o = reactExports.useRef(null), b = reactExports.useRef(null), L2 = reactExports.useRef(M2), U2 = reactExports.useRef(q2), I2 = reactExports.useRef(), i = reactExports.useRef(t2), f2 = se(m2), Q2 = reactExports.useRef(false), B2 = reactExports.useRef(false);
  k(() => {
    let p2 = loader.init();
    return p2.then((R2) => (d.current = R2) && w2(false)).catch((R2) => R2?.type !== "cancelation" && console.error("Monaco initialization: error:", R2)), () => o.current ? pe2() : p2.cancel();
  }), l(() => {
    let p2 = h(d.current, e || t2 || "", r2 || a || "", m2 || n2 || "");
    p2 !== o.current?.getModel() && (y2 && _.set(f2, o.current?.saveViewState()), o.current?.setModel(p2), y2 && o.current?.restoreViewState(_.get(m2)));
  }, [m2], s), l(() => {
    o.current?.updateOptions(x2);
  }, [x2], s), l(() => {
    !o.current || t2 === void 0 || (o.current.getOption(d.current.editor.EditorOption.readOnly) ? o.current.setValue(t2) : t2 !== o.current.getValue() && (B2.current = true, o.current.executeEdits("", [{ range: o.current.getModel().getFullModelRange(), text: t2, forceMoveMarkers: true }]), o.current.pushUndoStop(), B2.current = false));
  }, [t2], s), l(() => {
    let p2 = o.current?.getModel();
    p2 && a && d.current?.editor.setModelLanguage(p2, a);
  }, [a], s), l(() => {
    g !== void 0 && o.current?.revealLine(g);
  }, [g], s), l(() => {
    d.current?.editor.setTheme(E2);
  }, [E2], s);
  let X2 = reactExports.useCallback(() => {
    if (!(!b.current || !d.current) && !Q2.current) {
      U2.current(d.current);
      let p2 = m2 || n2, R2 = h(d.current, t2 || e || "", r2 || a || "", p2 || "");
      o.current = d.current?.editor.create(b.current, { model: R2, automaticLayout: true, ...x2 }, P2), y2 && o.current.restoreViewState(_.get(p2)), d.current.editor.setTheme(E2), g !== void 0 && o.current.revealLine(g), u2(true), Q2.current = true;
    }
  }, [e, r2, n2, t2, a, m2, x2, P2, y2, E2, g]);
  reactExports.useEffect(() => {
    s && L2.current(o.current, d.current);
  }, [s]), reactExports.useEffect(() => {
    !c && !s && X2();
  }, [c, s, X2]), i.current = t2, reactExports.useEffect(() => {
    s && O2 && (I2.current?.dispose(), I2.current = o.current?.onDidChangeModelContent((p2) => {
      B2.current || O2(o.current.getValue(), p2);
    }));
  }, [s, O2]), reactExports.useEffect(() => {
    if (s) {
      let p2 = d.current.editor.onDidChangeMarkers((R2) => {
        let G2 = o.current.getModel()?.uri;
        if (G2 && R2.find((J2) => J2.path === G2.path)) {
          let J2 = d.current.editor.getModelMarkers({ resource: G2 });
          T2?.(J2);
        }
      });
      return () => {
        p2?.dispose();
      };
    }
    return () => {
    };
  }, [s, T2]);
  function pe2() {
    I2.current?.dispose(), V2 ? y2 && _.set(m2, o.current.saveViewState()) : o.current.getModel()?.dispose(), o.current.dispose();
  }
  return React.createElement(H, { width: z2, height: F2, isEditorReady: s, loading: N2, _ref: b, className: j, wrapperProps: A2 });
}
var fe = Ve;
var de = reactExports.memo(fe);
var Ft = de;
function EditorPanel({ onEditorMount } = {}) {
  const { state, dispatch } = useApp();
  const editorRef = reactExports.useRef(null);
  const activeTab = state.openTabs.find((t2) => t2.path === state.activeTabPath);
  const handleMount = reactExports.useCallback((editor) => {
    editorRef.current = editor;
    onEditorMount?.(editor);
    editor.onDidChangeCursorSelection((e) => {
      const model = editor.getModel();
      if (!model) return;
      const sel = e.selection;
      const text = model.getValueInRange(sel);
      dispatch({
        type: "SET_EDITOR_SELECTION",
        selection: text.trim() ? {
          path: activeTab?.path,
          text,
          startLine: sel.startLineNumber,
          startCol: sel.startColumn,
          endLine: sel.endLineNumber,
          endCol: sel.endColumn
        } : null
      });
    });
    editor.addCommand(
      // Ctrl+S / Cmd+S
      2048 + 49,
      // monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS
      () => saveFile(editor.getValue())
    );
    editor.addCommand(
      2048 + 41,
      // CtrlCmd + K
      () => {
        const pos = editor.getPosition();
        const sel = editor.getSelection();
        const model = editor.getModel();
        const selectedText = model ? model.getValueInRange(sel) : "";
        const lineHeight = 22;
        const scrollTop = editor.getScrollTop();
        const top = pos ? Math.max(10, (pos.lineNumber - 1) * lineHeight - scrollTop + lineHeight) : 80;
        window.dispatchEvent(new CustomEvent("kendr:inline-edit", {
          detail: { top, path: activeTab?.path, selectedText: selectedText.trim() }
        }));
      }
    );
  }, [activeTab?.path, onEditorMount]);
  const saveFile = reactExports.useCallback(async (content) => {
    if (!activeTab) return;
    const api = window.kendrAPI;
    if (!api) return;
    const result = await api.fs.writeFile(activeTab.path, content);
    if (result.ok) {
      dispatch({ type: "MARK_TAB_MODIFIED", path: activeTab.path, modified: false });
    }
  }, [activeTab, dispatch]);
  const handleChange = reactExports.useCallback((value) => {
    if (!activeTab) return;
    dispatch({ type: "MARK_TAB_MODIFIED", path: activeTab.path, modified: true });
    const tabs = window.__tabContents = window.__tabContents || {};
    tabs[activeTab.path] = value;
  }, [activeTab, dispatch]);
  if (!activeTab) return null;
  const savedContent = window.__tabContents?.[activeTab.path] ?? activeTab.content ?? "";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "editor-panel", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "editor-breadcrumb", children: [
      activeTab.path.split(/[\\/]/).map((part, i, arr) => /* @__PURE__ */ jsxRuntimeExports.jsxs(React.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: i === arr.length - 1 ? "breadcrumb-file" : "breadcrumb-dir", children: part }),
        i < arr.length - 1 && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "breadcrumb-sep", children: "/" })
      ] }, i)),
      activeTab.modified && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "breadcrumb-modified", children: "●" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      Ft,
      {
        height: "100%",
        language: activeTab.language || "plaintext",
        value: savedContent,
        theme: "vs-dark",
        onMount: handleMount,
        onChange: handleChange,
        options: {
          fontSize: 14,
          fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', monospace",
          fontLigatures: true,
          lineHeight: 22,
          minimap: { enabled: true, scale: 1 },
          scrollBeyondLastLine: false,
          renderWhitespace: "selection",
          bracketPairColorization: { enabled: true },
          smoothScrolling: true,
          cursorBlinking: "smooth",
          cursorSmoothCaretAnimation: "on",
          padding: { top: 10, bottom: 10 },
          wordWrap: "off",
          tabSize: 2,
          insertSpaces: true,
          renderLineHighlight: "all",
          scrollbar: {
            verticalScrollbarSize: 8,
            horizontalScrollbarSize: 8
          },
          overviewRulerBorder: false,
          hideCursorInOverviewRuler: true,
          glyphMargin: false,
          folding: true,
          lineNumbersMinChars: 3
        }
      }
    )
  ] });
}
const FILE_ICONS = {
  js: "⚡",
  jsx: "⚛",
  ts: "🔷",
  tsx: "⚛",
  py: "🐍",
  json: "{}",
  md: "📝",
  html: "🌐",
  css: "🎨",
  yml: "⚙",
  yaml: "⚙",
  sh: "💻",
  rs: "⚙",
  go: "🐹",
  java: "☕",
  sql: "🗄",
  txt: "📄",
  env: "🔐",
  toml: "⚙",
  xml: "📋"
};
function TabBar() {
  const { state, dispatch } = useApp();
  if (state.openTabs.length === 0) return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "tab-bar tab-bar--empty", children: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "tab-bar-hint", children: "Open a file from the explorer or let the AI create one" }) });
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "tab-bar", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "tabs-scroll", children: state.openTabs.map((tab) => {
    const ext = tab.name.split(".").pop()?.toLowerCase() || "";
    const icon = FILE_ICONS[ext] || "📄";
    const isActive = tab.path === state.activeTabPath;
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: `tab ${isActive ? "tab--active" : ""} ${tab.modified ? "tab--modified" : ""}`,
        onClick: () => dispatch({ type: "SET_ACTIVE_TAB", path: tab.path }),
        title: tab.path,
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "tab-icon", children: icon }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "tab-name", children: tab.name }),
          tab.modified && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "tab-dot" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: "tab-close",
              onClick: (e) => {
                e.stopPropagation();
                dispatch({ type: "CLOSE_TAB", path: tab.path });
              },
              title: "Close",
              children: "×"
            }
          )
        ]
      },
      tab.path
    );
  }) }) });
}
const scriptRel = function detectScriptRel() {
  const relList = typeof document !== "undefined" && document.createElement("link").relList;
  return relList && relList.supports && relList.supports("modulepreload") ? "modulepreload" : "preload";
}();
const assetsURL = function(dep, importerUrl) {
  return new URL(dep, importerUrl).href;
};
const seen = {};
const __vitePreload = function preload(baseModule, deps, importerUrl) {
  let promise = Promise.resolve();
  if (deps && deps.length > 0) {
    const links = document.getElementsByTagName("link");
    const cspNonceMeta = document.querySelector(
      "meta[property=csp-nonce]"
    );
    const cspNonce = cspNonceMeta?.nonce || cspNonceMeta?.getAttribute("nonce");
    promise = Promise.allSettled(
      deps.map((dep) => {
        dep = assetsURL(dep, importerUrl);
        if (dep in seen) return;
        seen[dep] = true;
        const isCss = dep.endsWith(".css");
        const cssSelector = isCss ? '[rel="stylesheet"]' : "";
        const isBaseRelative = !!importerUrl;
        if (isBaseRelative) {
          for (let i = links.length - 1; i >= 0; i--) {
            const link2 = links[i];
            if (link2.href === dep && (!isCss || link2.rel === "stylesheet")) {
              return;
            }
          }
        } else if (document.querySelector(`link[href="${dep}"]${cssSelector}`)) {
          return;
        }
        const link = document.createElement("link");
        link.rel = isCss ? "stylesheet" : scriptRel;
        if (!isCss) {
          link.as = "script";
        }
        link.crossOrigin = "";
        link.href = dep;
        if (cspNonce) {
          link.setAttribute("nonce", cspNonce);
        }
        document.head.appendChild(link);
        if (isCss) {
          return new Promise((res, rej) => {
            link.addEventListener("load", res);
            link.addEventListener(
              "error",
              () => rej(new Error(`Unable to preload CSS for ${dep}`))
            );
          });
        }
      })
    );
  }
  function handlePreloadError(err) {
    const e = new Event("vite:preloadError", {
      cancelable: true
    });
    e.payload = err;
    window.dispatchEvent(e);
    if (!e.defaultPrevented) {
      throw err;
    }
  }
  return promise.then((res) => {
    for (const item of res || []) {
      if (item.status !== "rejected") continue;
      handlePreloadError(item.reason);
    }
    return baseModule().catch(handlePreloadError);
  });
};
function TerminalPanel() {
  const { state, dispatch } = useApp();
  const containerRef = reactExports.useRef(null);
  const termRef = reactExports.useRef(null);
  const fitRef = reactExports.useRef(null);
  const ptyIdRef = reactExports.useRef(null);
  const [loading, setLoading] = reactExports.useState(true);
  const [error, setError] = reactExports.useState(null);
  reactExports.useEffect(() => {
    let cancelled = false;
    async function init2() {
      const api = window.kendrAPI;
      if (!api) {
        setError("Electron API not available");
        setLoading(false);
        return;
      }
      try {
        const { Terminal } = await __vitePreload(async () => {
          const { Terminal: Terminal2 } = await import("./xterm-B3XbghfL.js").then((n2) => n2.x);
          return { Terminal: Terminal2 };
        }, true ? [] : void 0, import.meta.url);
        const { FitAddon } = await __vitePreload(async () => {
          const { FitAddon: FitAddon2 } = await import("./addon-fit-D14XCO-b.js").then((n2) => n2.a);
          return { FitAddon: FitAddon2 };
        }, true ? [] : void 0, import.meta.url);
        const { WebLinksAddon } = await __vitePreload(async () => {
          const { WebLinksAddon: WebLinksAddon2 } = await import("./addon-web-links-C2J5duG4.js").then((n2) => n2.a);
          return { WebLinksAddon: WebLinksAddon2 };
        }, true ? [] : void 0, import.meta.url);
        if (cancelled) return;
        const term = new Terminal({
          theme: {
            background: "#1e1e1e",
            foreground: "#cccccc",
            cursor: "#aeafad",
            selectionBackground: "#264f78",
            black: "#1e1e1e",
            brightBlack: "#808080",
            red: "#f44747",
            brightRed: "#f44747",
            green: "#89d185",
            brightGreen: "#b5cea8",
            yellow: "#dcdcaa",
            brightYellow: "#dcdcaa",
            blue: "#569cd6",
            brightBlue: "#9cdcfe",
            magenta: "#c586c0",
            brightMagenta: "#d7ba7d",
            cyan: "#4ec9b0",
            brightCyan: "#4ec9b0",
            white: "#d4d4d4",
            brightWhite: "#e8e8e8"
          },
          fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', monospace",
          fontSize: 13,
          lineHeight: 1.4,
          cursorBlink: true,
          cursorStyle: "block",
          allowTransparency: true,
          scrollback: 5e3
        });
        const fit = new FitAddon();
        term.loadAddon(fit);
        term.loadAddon(new WebLinksAddon());
        term.open(containerRef.current);
        fit.fit();
        termRef.current = term;
        fitRef.current = fit;
        const result = await api.pty.create({
          cwd: state.projectRoot || void 0,
          cols: term.cols,
          rows: term.rows
        });
        if (result.error) {
          term.writeln(`\x1B[31mFailed to create terminal: ${result.error}\x1B[0m`);
          setLoading(false);
          return;
        }
        ptyIdRef.current = result.id;
        window.__kendrPtyId = result.id;
        const unsubData = api.pty.onData(result.id, (data) => {
          term.write(data);
        });
        const unsubExit = api.pty.onExit(result.id, () => {
          term.writeln("\r\n\x1B[33m[Process exited]\x1B[0m");
        });
        term.onData((data) => {
          api.pty.write(result.id, data);
        });
        const observer = new ResizeObserver(() => {
          fit.fit();
          api.pty.resize(result.id, term.cols, term.rows);
        });
        observer.observe(containerRef.current);
        setLoading(false);
        const onRunCmd = (e) => {
          if (ptyIdRef.current) api.pty.write(ptyIdRef.current, e.detail.command + "\r");
        };
        window.addEventListener("kendr:run-command", onRunCmd);
        return () => {
          window.removeEventListener("kendr:run-command", onRunCmd);
          unsubData?.();
          unsubExit?.();
          observer.disconnect();
          api.pty.kill(result.id);
          window.__kendrPtyId = null;
          term.dispose();
        };
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      }
    }
    const cleanup = init2();
    return () => {
      cancelled = true;
      cleanup?.then?.((fn) => fn?.());
    };
  }, []);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "terminal-panel", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "terminal-header", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "terminal-title", children: "Terminal" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "terminal-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "icon-btn", title: "New terminal", onClick: () => {
          if (ptyIdRef.current) window.kendrAPI?.pty.kill(ptyIdRef.current);
          termRef.current?.dispose();
          ptyIdRef.current = null;
          termRef.current = null;
        }, children: "+" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "icon-btn",
            title: "Close terminal (Ctrl+`)",
            onClick: () => dispatch({ type: "SET_TERMINAL", open: false }),
            children: "×"
          }
        )
      ] })
    ] }),
    loading && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "terminal-loading", children: "Initializing terminal…" }),
    error && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "terminal-error", children: [
      error,
      " – node-pty may not be installed"
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: containerRef, className: "terminal-xterm", style: { opacity: loading ? 0 : 1 } })
  ] });
}
const LANG_MAP = {
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  py: "python",
  json: "json",
  md: "markdown",
  html: "html",
  css: "css",
  yml: "yaml",
  yaml: "yaml",
  sh: "shell",
  rs: "rust",
  go: "go",
  rb: "ruby",
  php: "php",
  java: "java",
  cpp: "cpp",
  c: "c",
  sql: "sql",
  toml: "toml"
};
function extractCode(text) {
  const m2 = text.match(/```(?:\w*)\n?([\s\S]*?)```/);
  return m2 ? m2[1].trimEnd() : text.trim();
}
function stepIcon(step) {
  const msg = (step.message || step.agent || step.reason || "").toLowerCase();
  if (msg.match(/read|open|load|fetch.*file/)) return "📄";
  if (msg.match(/write|edit|creat|modif|sav/)) return "✏️";
  if (msg.match(/run|exec|command|bash|shell|terminal/)) return "⚡";
  if (msg.match(/search|grep|find|look/)) return "🔍";
  if (msg.match(/web|http|url|browse/)) return "🌐";
  if (msg.match(/test/)) return "🧪";
  if (msg.match(/git/)) return "🔀";
  return "🤖";
}
function AIComposer({ editorInstanceRef }) {
  const { state: app, dispatch: appDispatch, openFile, refreshModelInventory } = useApp();
  const [mode, setMode] = reactExports.useState("agent");
  const [messages, setMessages] = reactExports.useState([]);
  const [diffPreviewPath, setDiffPreviewPath] = reactExports.useState("");
  const [input, setInput] = reactExports.useState("");
  const [streaming, setStreaming] = reactExports.useState(false);
  const [awaitingContext, setAwaitingContext] = reactExports.useState(null);
  const [attachedFiles, setAttachedFiles] = reactExports.useState([]);
  const [mentionAnchor, setMentionAnchor] = reactExports.useState(null);
  const [applyDiff, setApplyDiff] = reactExports.useState(null);
  const [editPrompt, setEditPrompt] = reactExports.useState("");
  const [editStreaming, setEditStreaming] = reactExports.useState(false);
  const [editDiff, setEditDiff] = reactExports.useState(null);
  const [editPhase, setEditPhase] = reactExports.useState("input");
  const esRef = reactExports.useRef(null);
  const threadEndRef = reactExports.useRef(null);
  const inputRef = reactExports.useRef(null);
  const chatId = reactExports.useRef(`comp-${Date.now()}`).current;
  const mirroredActivityIdsRef = reactExports.useRef([]);
  const apiBase = app.backendUrl || "http://127.0.0.1:2151";
  const activeTab = app.openTabs.find((t2) => t2.path === app.activeTabPath);
  const selection = app.editorSelection;
  const selectedModelMeta = resolveSelectedModel(app.selectedModel);
  const modelInventory = app.modelInventory;
  reactExports.useEffect(() => {
    refreshModelInventory(false);
  }, [refreshModelInventory]);
  reactExports.useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
  reactExports.useEffect(() => {
    const entries = messages.filter(shouldMirrorActivityMessage).map((msg) => buildActivityEntry(msg, { id: `project:${msg.id}`, source: "project" })).filter(Boolean);
    const nextIds = new Set(entries.map((entry) => entry.id));
    for (const entry of entries) {
      appDispatch({ type: "UPSERT_ACTIVITY_ENTRY", entry });
    }
    const removedIds = mirroredActivityIdsRef.current.filter((id2) => !nextIds.has(id2));
    if (removedIds.length) {
      appDispatch({ type: "REMOVE_ACTIVITY_ENTRIES", ids: removedIds });
    }
    mirroredActivityIdsRef.current = Array.from(nextIds);
  }, [messages, appDispatch]);
  reactExports.useEffect(() => {
    const toEdit = () => {
      setMode("edit");
      setEditPhase("input");
    };
    const setModeEvt = (e) => {
      if (e.detail) {
        setMode(e.detail);
        if (e.detail === "edit") setEditPhase("input");
      }
    };
    const inlineSubmit = (e) => {
      const { instruction } = e.detail || {};
      if (!instruction) return;
      setMode("edit");
      setEditPhase("input");
      setEditPrompt(instruction);
      setTimeout(() => window.dispatchEvent(new CustomEvent("kendr:composer-edit-submit")), 60);
    };
    window.addEventListener("kendr:composer-edit", toEdit);
    window.addEventListener("kendr:composer-set-mode", setModeEvt);
    window.addEventListener("kendr:inline-edit-submit", inlineSubmit);
    return () => {
      window.removeEventListener("kendr:composer-edit", toEdit);
      window.removeEventListener("kendr:composer-set-mode", setModeEvt);
      window.removeEventListener("kendr:inline-edit-submit", inlineSubmit);
    };
  }, []);
  const editPromptRef = reactExports.useRef(editPrompt);
  editPromptRef.current = editPrompt;
  const sendEditRef = reactExports.useRef(null);
  reactExports.useEffect(() => {
    const handler = () => sendEditRef.current?.();
    window.addEventListener("kendr:composer-edit-submit", handler);
    return () => window.removeEventListener("kendr:composer-edit-submit", handler);
  }, []);
  const runSSE = reactExports.useCallback(async ({ text, chatIdOverride, requestMode = "agent", resumeContext = null, onStep, onActivity, onResult, onAwaiting, onDone, onError }) => {
    const runId = `comp-${Date.now().toString(36)}`;
    const isProjectAgent = !!app.projectRoot;
    const selected = resolveSelectedModel(app.selectedModel);
    const endpoint = resumeContext ? `${apiBase}/api/chat/resume` : `${apiBase}/api/chat`;
    const payload = resumeContext ? {
      run_id: resumeContext.runId,
      workflow_id: resumeContext.workflowId,
      text,
      channel: isProjectAgent ? "project_ui" : "webchat"
    } : {
      text,
      channel: isProjectAgent ? "project_ui" : "webchat",
      sender_id: isProjectAgent ? "project_ui_user" : "composer",
      chat_id: chatIdOverride || chatId,
      run_id: runId,
      working_directory: app.projectRoot || void 0,
      project_root: app.projectRoot || void 0,
      provider: selected.provider || void 0,
      model: selected.model || void 0,
      execution_mode: requestMode === "plan" ? "plan" : void 0,
      planner_mode: requestMode === "plan" ? "always" : void 0,
      auto_approve_plan: requestMode === "plan" ? false : void 0
    };
    let resp;
    try {
      resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } catch (e) {
      refreshModelInventory(true);
      onError?.(`Network error: ${e.message}`);
      return;
    }
    if (!resp.ok) {
      refreshModelInventory(true);
      onError?.(`Backend error: ${resp.statusText}`);
      return;
    }
    const { run_id: srvId } = await resp.json().catch(() => ({}));
    const effectiveId = srvId || runId;
    esRef.current?.close();
    const es = new EventSource(`${apiBase}/api/stream?run_id=${encodeURIComponent(effectiveId)}`);
    esRef.current = es;
    let lastResult = "";
    let stepCount = 0;
    let awaiting = false;
    let failed = false;
    es.addEventListener("activity", (e) => {
      try {
        const data = JSON.parse(e.data);
        onActivity?.({
          id: data.id || `activity-${Date.now()}`,
          title: data.title || data.kind || "Activity",
          detail: data.detail || data.command || "",
          kind: data.kind || "activity",
          status: data.status || "running",
          command: data.command || "",
          cwd: data.cwd || "",
          actor: data.actor || "",
          durationLabel: data.duration_label || "",
          exitCode: data.exit_code
        });
      } catch {
      }
    });
    es.addEventListener("step", (e) => {
      try {
        const step = JSON.parse(e.data);
        onStep?.({
          stepId: step.step_id || step.id || `step-${++stepCount}`,
          agent: step.agent || step.name || "agent",
          status: step.status || "running",
          message: step.message || "",
          reason: step.reason || "",
          durationLabel: step.duration_label || ""
        });
      } catch {
      }
    });
    es.addEventListener("result", (e) => {
      try {
        const d = JSON.parse(e.data);
        lastResult = d.final_output || d.output || d.draft_response || d.response || "";
        awaiting = !!(d.awaiting_user_input || d.plan_waiting_for_approval || d.plan_needs_clarification || d.pending_user_input_kind || d.approval_pending_scope || d.pending_user_question || d.approval_request && Object.keys(d.approval_request).length > 0);
        if (awaiting) {
          onAwaiting?.({
            output: lastResult,
            checklist: extractChecklist$1(d),
            runId: d.run_id || effectiveId,
            workflowId: d.workflow_id || effectiveId,
            prompt: d.pending_user_question || lastResult || "Waiting for your input.",
            kind: d.pending_user_input_kind || "",
            scope: d.approval_pending_scope || "",
            approvalRequest: d.approval_request || null
          });
        } else {
          onResult?.(lastResult);
        }
      } catch {
      }
    });
    es.addEventListener("done", () => {
      if (failed) return;
      es.close();
      onDone?.({ output: lastResult, awaiting });
    });
    es.addEventListener("error", (e) => {
      if (failed) return;
      failed = true;
      refreshModelInventory(true);
      try {
        const d = JSON.parse(e.data);
        onError?.(d.message || "Run failed");
      } catch {
      }
      es.close();
    });
    es.onerror = () => {
      if (failed) return;
      failed = true;
      refreshModelInventory(true);
      onError?.("Run failed");
      es.close();
    };
  }, [apiBase, chatId, app.projectRoot, app.selectedModel, refreshModelInventory]);
  const stopStream = () => esRef.current?.close();
  const openArtifact = reactExports.useCallback(async (item) => {
    const filePath = String(item?.path || "").trim();
    if (!filePath) return;
    await openFile(filePath);
  }, [openFile]);
  const reviewArtifact = reactExports.useCallback((item) => {
    const filePath = String(item?.path || "").trim();
    if (!filePath) return;
    setDiffPreviewPath(filePath);
  }, []);
  const buildContextPrompt = reactExports.useCallback((userText) => {
    let ctx = userText;
    if (mode === "agent") {
      ctx = "[IDE agent mode]\n- Work like a coding agent inside an IDE.\n- Inspect files and context before changing code.\n- Keep progress updates and final answers concise, direct, and action-oriented.\n- If you propose code changes, prefer complete code blocks with filenames when that helps apply them cleanly.\n- Use the current project and file context instead of answering generically.\n\n" + userText;
    } else if (mode === "plan") {
      ctx = "[IDE plan mode]\n- Inspect project context before acting.\n- Produce a concise implementation plan first.\n- Wait for approval before writing code.\n- Keep the plan actionable and sequenced.\n\n" + userText;
    }
    if (activeTab) {
      const content = window.__tabContents?.[activeTab.path] ?? activeTab.content ?? "";
      ctx += `

[Active file: ${activeTab.name}]
\`\`\`${activeTab.language || ""}
${content.slice(0, 4e3)}
\`\`\``;
    }
    if (selection?.text && selection.path === activeTab?.path) {
      ctx += `

[Selected (lines ${selection.startLine}–${selection.endLine})]
\`\`\`
${selection.text}
\`\`\``;
    }
    for (const f2 of attachedFiles) {
      const c = window.__tabContents?.[f2.path] ?? "";
      if (c) ctx += `

[@${f2.name}]
\`\`\`
${c.slice(0, 2e3)}
\`\`\``;
    }
    return ctx;
  }, [activeTab, selection, attachedFiles, mode]);
  const composerModelBadge = (() => {
    if (selectedModelMeta.model) {
      return {
        primary: `Selected · ${selectedModelMeta.label}`,
        secondary: app.projectRoot ? `Project · ${basename$1(app.projectRoot)}` : ""
      };
    }
    const configuredProvider = String(modelInventory?.configured_provider || "").trim().toLowerCase();
    const configuredModel = String(modelInventory?.configured_model || "").trim();
    const activeProvider = String(modelInventory?.active_provider || "").trim().toLowerCase();
    const activeModel = String(modelInventory?.active_model || "").trim();
    if (configuredProvider && configuredModel) {
      const configuredLabel = resolveSelectedModel(`${configuredProvider}/${configuredModel}`).label;
      const configuredReady = modelInventory?.configured_provider_ready !== false;
      const activeDiffers = configuredProvider !== activeProvider || configuredModel !== activeModel;
      return {
        primary: `${configuredReady ? "Configured" : "Configured offline"} · ${configuredLabel}`,
        secondary: activeDiffers && activeProvider && activeModel ? `Active · ${resolveSelectedModel(`${activeProvider}/${activeModel}`).label}` : app.projectRoot ? `Project · ${basename$1(app.projectRoot)}` : ""
      };
    }
    return {
      primary: "Auto · Backend default",
      secondary: app.projectRoot ? `Project · ${basename$1(app.projectRoot)}` : ""
    };
  })();
  const send = reactExports.useCallback(async (textOverride = "", isResume = false) => {
    const text = String(textOverride || input).trim();
    if (!text || streaming) return;
    setInput("");
    setMentionAnchor(null);
    const resumeMessageId = String(awaitingContext?.messageId || "").trim();
    const preserveInlineBubble = isResume && resumeMessageId && !isSkillApproval(awaitingContext?.kind, awaitingContext?.approvalRequest);
    const msgId = isResume && resumeMessageId && !preserveInlineBubble ? resumeMessageId : `a-${Date.now()}`;
    setMessages((messages2) => {
      let next = [...messages2, { id: `u-${Date.now()}`, role: "user", content: text }];
      if (preserveInlineBubble && resumeMessageId) {
        const normalizedReply = text.toLowerCase();
        const approvalState = normalizedReply === "approve" ? "approved" : normalizedReply === "cancel" ? "rejected" : "suggested";
        next = next.map((message) => message.id === resumeMessageId ? { ...message, status: "done", approvalState } : message);
      }
      if (isResume && resumeMessageId && !preserveInlineBubble) {
        next = next.map((message) => message.id === msgId ? { ...message, content: "", steps: [], progress: [], checklist: [], status: "thinking", approvalRequest: null, approvalScope: "", approvalKind: "" } : message);
      } else {
        next.push({ id: msgId, role: "assistant", content: "", steps: [], progress: [], checklist: [], status: "thinking", mode, approvalRequest: null, approvalScope: "", approvalKind: "" });
      }
      return next;
    });
    setStreaming(true);
    setAwaitingContext(null);
    try {
      await runSSE({
        text: isResume ? text : buildContextPrompt(text),
        requestMode: mode,
        resumeContext: isResume ? awaitingContext : null,
        onStep: (step) => setMessages((m2) => m2.map((msg) => {
          if (msg.id !== msgId) return msg;
          const steps = [...msg.steps || []];
          const idx = steps.findIndex((s) => s.stepId === step.stepId);
          if (idx >= 0) steps[idx] = step;
          else steps.push(step);
          return { ...msg, steps };
        })),
        onActivity: (item) => setMessages((messages2) => messages2.map((message) => {
          if (message.id !== msgId) return message;
          const prev = Array.isArray(message.progress) ? message.progress : [];
          return { ...message, progress: [item, ...prev].slice(0, 16) };
        })),
        onResult: (out) => setMessages((m2) => m2.map(
          (msg) => msg.id === msgId ? { ...msg, content: out, status: "streaming" } : msg
        )),
        onAwaiting: (data) => {
          setAwaitingContext({ ...data, messageId: msgId });
          setMessages((messages2) => messages2.map((message) => message.id === msgId ? {
            ...message,
            content: data.output,
            checklist: data.checklist,
            status: "awaiting",
            approvalRequest: data.approvalRequest || null,
            approvalScope: data.scope || "",
            approvalKind: data.kind || "",
            approvalState: "pending"
          } : message));
        },
        onDone: ({ output, awaiting }) => {
          if (awaiting) {
            setStreaming(false);
            return;
          }
          setMessages((m2) => m2.map(
            (msg) => msg.id === msgId ? { ...msg, content: output || msg.content, status: "done" } : msg
          ));
          setStreaming(false);
        },
        onError: (err) => {
          setAwaitingContext(null);
          setMessages((m2) => m2.map(
            (msg) => msg.id === msgId ? { ...msg, content: err, status: "error" } : msg
          ));
          setStreaming(false);
        }
      });
    } catch (e) {
      setMessages((m2) => m2.map(
        (msg) => msg.id === msgId ? { ...msg, content: `Error: ${e.message}`, status: "error" } : msg
      ));
      setStreaming(false);
    }
  }, [input, streaming, runSSE, buildContextPrompt, mode, awaitingContext]);
  const sendEdit = reactExports.useCallback(async () => {
    const prompt2 = editPromptRef.current.trim();
    if (!prompt2 || editStreaming || !activeTab) return;
    const codeToEdit = selection?.path === activeTab.path && selection?.text ? selection.text : window.__tabContents?.[activeTab.path] ?? activeTab.content ?? "";
    const lang = LANG_MAP[activeTab.name?.split(".").pop()?.toLowerCase()] || "plaintext";
    const fullPrompt = `Edit the following code from "${activeTab.name}":

\`\`\`${lang}
${codeToEdit}
\`\`\`

Instruction: ${prompt2}

Return ONLY the complete modified code in a single code block. No explanation.`;
    setEditStreaming(true);
    setEditPhase("streaming");
    try {
      await runSSE({
        text: fullPrompt,
        chatIdOverride: `edit-${chatId}`,
        onDone: ({ output }) => {
          setEditStreaming(false);
          setEditDiff({ original: codeToEdit, modified: extractCode(output || ""), lang });
          setEditPhase("diff");
        },
        onError: () => {
          setEditStreaming(false);
          setEditPhase("input");
        }
      });
    } catch {
      setEditStreaming(false);
      setEditPhase("input");
    }
  }, [editStreaming, activeTab, selection, runSSE, chatId]);
  sendEditRef.current = sendEdit;
  const applyEdit = reactExports.useCallback(() => {
    const editor = editorInstanceRef?.current;
    if (!editor || !editDiff) return;
    const sel = app.editorSelection;
    if (sel?.text && sel.path === activeTab?.path) {
      editor.executeEdits("ai", [{
        range: { startLineNumber: sel.startLine, startColumn: sel.startCol, endLineNumber: sel.endLine, endColumn: sel.endCol },
        text: editDiff.modified
      }]);
    } else {
      editor.setValue(editDiff.modified);
    }
    if (activeTab) {
      window.kendrAPI?.fs.writeFile(activeTab.path, editor.getValue());
      appDispatch({ type: "MARK_TAB_MODIFIED", path: activeTab.path, modified: false });
    }
    setEditPhase("applied");
    setEditDiff(null);
    setEditPrompt("");
    setTimeout(() => setEditPhase("input"), 1800);
  }, [editDiff, editorInstanceRef, app.editorSelection, activeTab, appDispatch]);
  const handleApplyBlock = reactExports.useCallback(({ code, lang, filename }) => {
    const original = activeTab ? window.__tabContents?.[activeTab.path] ?? activeTab.content ?? "" : "";
    const targetPath = filename ? app.projectRoot ? `${app.projectRoot}/${filename}` : filename : activeTab?.path;
    setApplyDiff({ original, modified: code, lang: lang || "plaintext", filename, targetPath });
  }, [activeTab, app.projectRoot]);
  const acceptApply = reactExports.useCallback(async () => {
    if (!applyDiff) return;
    const editor = editorInstanceRef?.current;
    if (editor && applyDiff.targetPath === activeTab?.path) {
      editor.setValue(applyDiff.modified);
      window.kendrAPI?.fs.writeFile(applyDiff.targetPath, applyDiff.modified);
      appDispatch({ type: "MARK_TAB_MODIFIED", path: applyDiff.targetPath, modified: false });
    } else if (applyDiff.targetPath) {
      await window.kendrAPI?.fs.writeFile(applyDiff.targetPath, applyDiff.modified);
      if (applyDiff.filename) {
        const name = applyDiff.filename.split("/").pop();
        appDispatch({ type: "OPEN_TAB", tab: { path: applyDiff.targetPath, name, language: LANG_MAP[name.split(".").pop()?.toLowerCase()] || "plaintext", content: applyDiff.modified, modified: false } });
      }
    }
    setApplyDiff(null);
  }, [applyDiff, editorInstanceRef, activeTab, appDispatch]);
  const handleInputChange = (e) => {
    const val = e.target.value;
    setInput(val);
    const atIdx = val.lastIndexOf("@");
    if (atIdx !== -1 && (atIdx === 0 || /\s/.test(val[atIdx - 1]))) {
      const query = val.slice(atIdx + 1);
      if (!query.includes(" ") && !query.includes("\n")) {
        setMentionAnchor({ query, idx: atIdx });
        return;
      }
    }
    setMentionAnchor(null);
  };
  const pickMention = (tab) => {
    if (!mentionAnchor) return;
    const before = input.slice(0, mentionAnchor.idx);
    const after = input.slice(mentionAnchor.idx + 1 + mentionAnchor.query.length);
    setInput(`${before}@${tab.name} ${after}`);
    setAttachedFiles((f2) => [...f2.filter((x2) => x2.path !== tab.path), { path: tab.path, name: tab.name }]);
    setMentionAnchor(null);
    requestAnimationFrame(() => inputRef.current?.focus());
  };
  const handleKey = (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      send();
    }
    if (e.key === "Escape") setMentionAnchor(null);
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-panel", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      GitDiffPreview,
      {
        cwd: app.projectRoot,
        filePath: diffPreviewPath,
        onClose: () => setDiffPreviewPath(""),
        onOpenFile: (filePath) => openArtifact({ path: filePath })
      }
    ),
    applyDiff && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-apply-overlay", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-apply-bar", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-apply-title", children: applyDiff.filename ? `✨ Create ${applyDiff.filename}` : `✨ Edit ${activeTab?.name || "file"}` }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-apply-btns", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ac-accept-btn", onClick: acceptApply, children: "✓ Accept" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ac-reject-btn", onClick: () => setApplyDiff(null), children: "✕ Reject" })
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        we,
        {
          height: "calc(100% - 44px)",
          language: applyDiff.lang,
          original: applyDiff.original,
          modified: applyDiff.modified,
          theme: "vs-dark",
          options: { readOnly: true, minimap: { enabled: false }, fontSize: 12, lineNumbers: "off", scrollBeyondLastLine: false, renderSideBySide: false, padding: { top: 6 }, overviewRulerBorder: false }
        }
      )
    ] }),
    !applyDiff && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-header", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-mode-tabs", children: [["agent", "Agent"], ["plan", "Plan"], ["chat", "Chat"], ["edit", "Edit"]].map(([id2, label]) => /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: `ac-mode-tab ${mode === id2 ? "active" : ""}`,
            onClick: () => {
              setMode(id2);
              if (id2 === "edit") setEditPhase("input");
            },
            children: label
          },
          id2
        )) }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-model-badge", title: composerModelBadge.primary, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `ac-model-dot ${selectedModelMeta.isLocal || String(modelInventory?.configured_provider || "").toLowerCase() === "ollama" ? "local" : ""}` }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-model-primary", children: composerModelBadge.primary }),
          composerModelBadge.secondary && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-model-secondary", children: composerModelBadge.secondary })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-header-right", children: [
          streaming && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-live-dot" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: "ac-header-btn",
              title: "New conversation",
              onClick: () => {
                setMessages([]);
                setAttachedFiles([]);
                setAwaitingContext(null);
              },
              children: "⊘"
            }
          )
        ] })
      ] }),
      (mode === "agent" || mode === "plan" || mode === "chat") && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        (activeTab || attachedFiles.length > 0) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-context-bar", children: [
          activeTab && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "ac-ctx-file", children: [
            "📄 ",
            activeTab.name
          ] }),
          selection?.text && selection.path === activeTab?.path && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "ac-ctx-sel", children: [
            selection.text.split("\n").length,
            "L"
          ] }),
          attachedFiles.map((f2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "ac-ctx-attach", children: [
            "@",
            f2.name,
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: () => setAttachedFiles((a) => a.filter((x2) => x2.path !== f2.path)), children: "×" })
          ] }, f2.path))
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-thread", children: [
          messages.length === 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-empty", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-empty-icon", children: mode === "agent" ? "✨" : mode === "plan" ? "🗺️" : "💬" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-empty-title", children: mode === "agent" ? "Agent" : mode === "plan" ? "Plan" : "Chat" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-empty-sub", children: mode === "agent" ? "The agent works against the current project like an IDE coding assistant. It can inspect files, run tasks, and prepare code edits with project context." : mode === "plan" ? "Plan mode inspects the project, proposes the work, and waits before implementation." : "Ask questions about code, get explanations, or request suggestions." }),
            activeTab && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-chips", children: (mode === "agent" ? ["Refactor this file", "Find and fix bugs", "Add TypeScript types", "Write unit tests"] : mode === "plan" ? ["Plan a refactor for this file", "Plan the bug fix work", "Outline implementation steps", "Break this task into milestones"] : ["Explain this code", "What does this do?", "How can I improve this?", "Find potential issues"]).map((s) => /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ac-chip", onClick: () => {
              setInput(s);
              inputRef.current?.focus();
            }, children: s }, s)) })
          ] }),
          messages.map((msg) => /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: `ac-msg ac-msg--${msg.role}`, children: msg.role === "user" ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-user-bubble", children: msg.content }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-asst-msg", children: [
            msg.steps?.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx(AgentSteps, { steps: msg.steps, live: streaming && msg.status !== "done" && msg.status !== "error" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(ComposerActivityCards, { progress: msg.progress, artifacts: msg.artifacts, onOpenItem: openArtifact, onReviewItem: reviewArtifact }),
            msg.checklist?.length > 0 && (msg.mode === "plan" || isPlanApprovalScope(msg.approvalScope, msg.approvalKind, msg.approvalRequest)) && /* @__PURE__ */ jsxRuntimeExports.jsx(
              ComposerPlanCard,
              {
                msg,
                onQuickReply: (reply) => send(reply, true),
                onSendSuggestion: (reply) => send(reply, true)
              }
            ),
            msg.status === "awaiting" && !isSkillApproval(msg.approvalKind, msg.approvalRequest) && !(msg.checklist?.length > 0 && (msg.mode === "plan" || isPlanApprovalScope(msg.approvalScope, msg.approvalKind, msg.approvalRequest))) && /* @__PURE__ */ jsxRuntimeExports.jsx(
              ComposerAwaitingCard,
              {
                msg,
                onQuickReply: (reply) => send(reply, true),
                onSendSuggestion: (reply) => send(reply, true)
              }
            ),
            msg.status === "thinking" && !msg.steps?.length ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-thinking-row", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "ac-thinking", children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", {}),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", {}),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", {})
              ] }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-thinking-label", children: "Thinking…" })
            ] }) : msg.status === "error" ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-error-msg", children: [
              "⚠ ",
              msg.content
            ] }) : msg.content && !(msg.status === "awaiting" && !isSkillApproval(msg.approvalKind, msg.approvalRequest)) && !(msg.checklist?.length > 0 && (msg.mode === "plan" || isPlanApprovalScope(msg.approvalScope, msg.approvalKind, msg.approvalRequest))) ? /* @__PURE__ */ jsxRuntimeExports.jsx(AgentResponse, { content: msg.content, onApply: mode === "agent" ? handleApplyBlock : null }) : null
          ] }) }, msg.id)),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: threadEndRef })
        ] }),
        mentionAnchor && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-mention-picker", children: app.openTabs.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-mention-empty", children: "No open files" }) : app.openTabs.filter((t2) => !mentionAnchor.query || t2.name.toLowerCase().includes(mentionAnchor.query.toLowerCase())).slice(0, 7).map((t2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "ac-mention-item", onMouseDown: () => pickMention(t2), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-mention-name", children: t2.name }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-mention-path", children: t2.path.replace(app.projectRoot || "", "").slice(-40) })
        ] }, t2.path)) }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-input-area", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "textarea",
            {
              ref: inputRef,
              className: "ac-input",
              placeholder: mode === "agent" ? "Ask the project agent to inspect, edit, debug, or explain code… (@ to mention files, Ctrl+Enter to send)" : mode === "plan" ? "Ask for a plan first. Kendr will inspect the project and wait before changing code… (Ctrl+Enter)" : "Ask about code… (Ctrl+Enter to send)",
              value: input,
              onChange: handleInputChange,
              onKeyDown: handleKey,
              rows: 3,
              disabled: streaming
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-input-footer", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-input-hint", children: "Ctrl+Enter" }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-flow-strip", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `ac-flow-chip ac-flow-chip--${mode}`, children: mode === "plan" ? "Plan first" : mode === "agent" ? "Project run" : "Chat" }),
              activeTab && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-flow-chip", children: activeTab.name })
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "button",
              {
                className: `ac-send-btn ${streaming ? "stop" : ""}`,
                onClick: streaming ? () => {
                  stopStream();
                  setStreaming(false);
                } : send,
                disabled: !streaming && !input.trim(),
                children: streaming ? /* @__PURE__ */ jsxRuntimeExports.jsx(StopIcon, {}) : /* @__PURE__ */ jsxRuntimeExports.jsx(SendIcon, {})
              }
            )
          ] })
        ] })
      ] }),
      mode === "edit" && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-edit", children: !activeTab ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-empty", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-empty-icon", children: "✏️" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-empty-sub", children: "Open a file in the editor to use Edit mode." })
      ] }) : editPhase === "diff" ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-diff-wrap", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-diff-toolbar", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "ac-diff-label", children: [
            "Proposed — ",
            activeTab.name
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ac-accept-btn", onClick: applyEdit, children: "✓ Accept" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ac-reject-btn", onClick: () => {
            setEditPhase("input");
            setEditDiff(null);
          }, children: "✕ Reject" })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          we,
          {
            height: "calc(100% - 44px)",
            language: editDiff.lang,
            original: editDiff.original,
            modified: editDiff.modified,
            theme: "vs-dark",
            options: { readOnly: true, minimap: { enabled: false }, fontSize: 12, lineNumbers: "off", scrollBeyondLastLine: false, renderSideBySide: false, padding: { top: 6 }, overviewRulerBorder: false }
          }
        )
      ] }) : editPhase === "applied" ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-empty", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-empty-icon", children: "✓" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-empty-title", style: { color: "var(--kc-teal)" }, children: "Changes applied!" })
      ] }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-edit-form", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-edit-context", children: selection?.text && selection.path === activeTab.path ? `✏ ${selection.text.split("\n").length} lines selected in ${activeTab.name}` : `✏ Editing entire file: ${activeTab.name}` }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "textarea",
          {
            className: "ac-edit-textarea",
            placeholder: "Describe the change…\ne.g. Add error handling, refactor to async/await, add TypeScript types",
            value: editPrompt,
            onChange: (e) => setEditPrompt(e.target.value),
            onKeyDown: (e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                sendEdit();
              }
            },
            rows: 7,
            disabled: editStreaming,
            autoFocus: true
          }
        ),
        editStreaming ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-progress", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-spinner" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Rewriting code…" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ac-stop-link", onClick: () => {
            stopStream();
            setEditStreaming(false);
            setEditPhase("input");
          }, children: "Stop" })
        ] }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "ac-run-btn", onClick: sendEdit, disabled: !editPrompt.trim(), children: [
          "✨ Apply Edit ",
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-hint-key", children: "Ctrl+Enter" })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-edit-hints", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Ctrl+Enter to run" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Select lines in editor to target a range" })
        ] })
      ] }) })
    ] })
  ] });
}
function AgentSteps({ steps, live }) {
  const [open, setOpen] = reactExports.useState(false);
  const running = steps.filter((s) => s.status === "running");
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "as-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "as-toggle", onClick: () => setOpen((o) => !o), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-toggle-left", children: live && running.length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-spinner" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-toggle-txt", children: running[0].message || "Working…" })
      ] }) : /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-check", children: "✓" }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "as-toggle-txt", children: [
          steps.length,
          " action",
          steps.length !== 1 ? "s" : ""
        ] })
      ] }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-chevron", children: open ? "▴" : "▾" })
    ] }),
    open && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "as-list", children: steps.map((s, i) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `as-step as-step--${s.status}`, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-step-icon", children: stepIcon(s) }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "as-step-body", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-step-msg", children: s.message || s.agent }),
        s.reason && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-step-reason", children: s.reason })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-step-meta", children: s.status === "running" ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-spinner as-spinner--sm" }) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "as-step-dur", children: s.durationLabel }) })
    ] }, s.stepId || i)) })
  ] });
}
function ComposerActivityCards({ progress, artifacts, onOpenItem, onReviewItem }) {
  const cards = summarizeRunArtifacts(progress, artifacts);
  if (!cards.length) return null;
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-grid", children: cards.map((card) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-activity-card kc-activity-card--${card.kind}`, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-activity-card-head", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-kind", children: card.kind }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-title", children: card.title })
      ] }),
      card.kind === "edit" && Array.isArray(card.items) && card.items.some((item) => item?.path) && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-action", onClick: () => onReviewItem?.(card.items.find((item) => item?.path)), children: "Review" })
    ] }),
    Array.isArray(card.items) && card.items.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-items", children: card.items.slice(0, 3).map((item) => item?.path ? /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-item kc-activity-card-item--action", onClick: () => onOpenItem?.(item), children: item.label }, `${item.path}-${item.label}`) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-activity-card-item", children: item.label }, item.label)) })
  ] }, `${card.kind}-${card.title}`)) });
}
function ComposerPlanCard({ msg, onQuickReply, onSendSuggestion }) {
  const [showSuggest, setShowSuggest] = reactExports.useState(false);
  const [draft, setDraft] = reactExports.useState("");
  const checklist = Array.isArray(msg.checklist) ? msg.checklist : [];
  if (!checklist.length) return null;
  const approvalRequest = msg.approvalRequest && typeof msg.approvalRequest === "object" ? msg.approvalRequest : {};
  const approvalActions = approvalRequest.actions && typeof approvalRequest.actions === "object" ? approvalRequest.actions : {};
  const awaiting = msg.status === "awaiting";
  const summary = String(approvalRequest.summary || msg.content || "").trim();
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-plan-card-head", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-plan-card-label", children: awaiting ? "Plan Ready" : "Plan" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-meta", children: [
        checklist.length,
        " task",
        checklist.length === 1 ? "" : "s"
      ] })
    ] }) }),
    summary && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-plan-card-summary", children: summary }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-plan-card-list", children: checklist.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-item", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-mark", children: item.done ? "✓" : item.status === "running" ? "…" : "·" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-body", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-row", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-checklist-step", children: [
            item.step,
            "."
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-checklist-text", children: item.title })
        ] }),
        item.detail && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-detail", children: item.detail })
      ] })
    ] }, `${item.step}-${item.title}`)) }),
    awaiting && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-plan-card-btn kc-plan-card-btn--approve", onClick: () => onQuickReply?.("approve"), children: approvalActions.accept_label || "Implement" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: `kc-plan-card-btn kc-plan-card-btn--ghost${showSuggest ? " kc-plan-card-btn--active" : ""}`,
            onClick: () => setShowSuggest((value) => !value),
            children: approvalActions.suggest_label || "Change Plan"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-plan-card-btn kc-plan-card-btn--reject", onClick: () => onQuickReply?.("cancel"), children: approvalActions.reject_label || "Reject" })
      ] }),
      showSuggest && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-suggest", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "textarea",
          {
            className: "kc-plan-card-input",
            rows: 3,
            placeholder: "Say what should change in the plan…",
            value: draft,
            onChange: (event) => setDraft(event.target.value)
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "kc-plan-card-btn kc-plan-card-btn--approve",
            disabled: !draft.trim(),
            onClick: () => {
              if (!draft.trim()) return;
              onSendSuggestion?.(draft);
              setDraft("");
              setShowSuggest(false);
            },
            children: "Send"
          }
        )
      ] })
    ] })
  ] });
}
function ComposerAwaitingCard({ msg, onQuickReply, onSendSuggestion }) {
  const [showSuggest, setShowSuggest] = reactExports.useState(false);
  const [draft, setDraft] = reactExports.useState("");
  const approvalRequest = msg.approvalRequest && typeof msg.approvalRequest === "object" ? msg.approvalRequest : {};
  const approvalActions = approvalRequest.actions && typeof approvalRequest.actions === "object" ? approvalRequest.actions : {};
  const title = approvalRequest.title || "Waiting for input";
  const summary = String(approvalRequest.summary || msg.content || "").trim();
  const sections = Array.isArray(approvalRequest.sections) ? approvalRequest.sections : [];
  const hasQuickActions = !!(approvalActions.accept_label || approvalActions.reject_label || approvalActions.suggest_label || msg.approvalScope);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-inline-approval", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-inline-approval-head", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-title", children: title }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-status", children: "awaiting" })
    ] }),
    summary && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-summary", children: /* @__PURE__ */ jsxRuntimeExports.jsx(AcText, { text: summary }) }),
    sections.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-sections", children: sections.map((section, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-inline-approval-section", children: [
      section.title && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-section-title", children: section.title }),
      Array.isArray(section.items) && section.items.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("ul", { className: "kc-inline-approval-list", children: section.items.map((item, itemIndex) => /* @__PURE__ */ jsxRuntimeExports.jsx("li", { children: item }, `${index2}-${itemIndex}`)) })
    ] }, `${section.title || "section"}-${index2}`)) }),
    approvalRequest.help_text && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-inline-approval-help", children: approvalRequest.help_text }),
    hasQuickActions ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-inline-approval-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-plan-card-btn kc-plan-card-btn--approve", onClick: () => onQuickReply?.("approve"), children: approvalActions.accept_label || "Approve" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: `kc-plan-card-btn kc-plan-card-btn--ghost${showSuggest ? " kc-plan-card-btn--active" : ""}`,
            onClick: () => setShowSuggest((value) => !value),
            children: approvalActions.suggest_label || "Reply"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-plan-card-btn kc-plan-card-btn--reject", onClick: () => onQuickReply?.("cancel"), children: approvalActions.reject_label || "Reject" })
      ] }),
      showSuggest && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-suggest", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "textarea",
          {
            className: "kc-plan-card-input",
            rows: 3,
            placeholder: "Type your reply…",
            value: draft,
            onChange: (event) => setDraft(event.target.value)
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "kc-plan-card-btn kc-plan-card-btn--approve",
            disabled: !draft.trim(),
            onClick: () => {
              if (!draft.trim()) return;
              onSendSuggestion?.(draft);
              setDraft("");
              setShowSuggest(false);
            },
            children: "Send"
          }
        )
      ] })
    ] }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-plan-card-suggest", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "textarea",
        {
          className: "kc-plan-card-input",
          rows: 3,
          placeholder: "Type your reply…",
          value: draft,
          onChange: (event) => setDraft(event.target.value)
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: "kc-plan-card-btn kc-plan-card-btn--approve",
          disabled: !draft.trim(),
          onClick: () => {
            if (!draft.trim()) return;
            onSendSuggestion?.(draft);
            setDraft("");
          },
          children: "Send reply"
        }
      )
    ] })
  ] });
}
function AgentResponse({ content, onApply }) {
  const parts = [];
  const re2 = /```(\w*)\n?([\s\S]*?)```/g;
  let last = 0, m2;
  while ((m2 = re2.exec(content)) !== null) {
    if (m2.index > last) parts.push({ t: "text", v: content.slice(last, m2.index) });
    parts.push({ t: "code", lang: m2[1], v: m2[2].trimEnd() });
    last = m2.index + m2[0].length;
  }
  if (last < content.length) parts.push({ t: "text", v: content.slice(last) });
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ac-md", children: parts.map(
    (p2, i) => p2.t === "code" ? /* @__PURE__ */ jsxRuntimeExports.jsx(AgentCodeBlock, { lang: p2.lang, code: p2.v, onApply }, i) : /* @__PURE__ */ jsxRuntimeExports.jsx(AcText, { text: p2.v }, i)
  ) });
}
function AgentCodeBlock({ lang, code, onApply }) {
  const [copied, setCopied] = reactExports.useState(false);
  const [applied, setApplied] = reactExports.useState(false);
  const firstLine = code.split("\n")[0];
  const filename = firstLine.match(/^[#/*\s]*(?:filename|file):\s*(.+)/i)?.[1]?.trim();
  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const apply = () => {
    onApply?.({ code, lang: lang || "plaintext", filename });
    setApplied(true);
    setTimeout(() => setApplied(false), 2e3);
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-code-block", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-code-header", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ac-code-lang", children: filename || lang || "code" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ac-code-actions", children: [
        onApply && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `ac-apply-chip ${applied ? "applied" : ""}`, onClick: apply, children: applied ? "✓ Applied" : "⊕ Apply" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ac-code-copy", onClick: copy, children: copied ? "✓" : "⧉" })
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "ac-code-body", children: /* @__PURE__ */ jsxRuntimeExports.jsx("code", { children: code }) })
  ] });
}
function AcText({ text }) {
  const html = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\*(.+?)\*/g, "<em>$1</em>").replace(/`([^`]+)`/g, '<code class="ac-inline-code">$1</code>').replace(/\n/g, "<br/>");
  return /* @__PURE__ */ jsxRuntimeExports.jsx("span", { dangerouslySetInnerHTML: { __html: html } });
}
function SendIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "14", height: "14", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("line", { x1: "22", y1: "2", x2: "11", y2: "13" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("polygon", { points: "22 2 15 22 11 13 2 9 22 2" })
  ] });
}
function StopIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("svg", { width: "12", height: "12", viewBox: "0 0 24 24", fill: "currentColor", children: /* @__PURE__ */ jsxRuntimeExports.jsx("rect", { x: "4", y: "4", width: "16", height: "16", rx: "2.5" }) });
}
const STORAGE_KEY = "kendr_run_configs_v2";
function loadConfigs() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}
const PRESETS = [
  { name: "npm dev", command: "npm run dev", icon: "🟢" },
  { name: "npm start", command: "npm start", icon: "🟢" },
  { name: "npm test", command: "npm test", icon: "🧪" },
  { name: "npm build", command: "npm run build", icon: "📦" },
  { name: "Python app", command: "python app.py", icon: "🐍" },
  { name: "Python main", command: "python main.py", icon: "🐍" },
  { name: "pytest", command: "pytest", icon: "🧪" },
  { name: "pip install", command: "pip install -r requirements.txt", icon: "📦" },
  { name: "go run", command: "go run .", icon: "🔵" },
  { name: "cargo run", command: "cargo run", icon: "🦀" }
];
function formatDuration(totalSeconds) {
  const s = Math.max(0, Number(totalSeconds) || 0);
  const h2 = Math.floor(s / 3600);
  const m2 = Math.floor(s % 3600 / 60);
  const sec = s % 60;
  if (h2 > 0) return `${h2}h ${m2}m ${sec}s`;
  if (m2 > 0) return `${m2}m ${sec}s`;
  return `${sec}s`;
}
function isShellProgressItem(item) {
  if (!item || typeof item !== "object") return false;
  const kind = String(item.kind || "").toLowerCase();
  const title = String(item.title || "").toLowerCase();
  const detail = String(item.detail || "").toLowerCase();
  const command = String(item.command || "").trim();
  if (command) return true;
  if (kind.includes("command") || kind.includes("shell")) return true;
  return /\bshell command\b|\brunning command\b|\bos[_\s-]?agent\b/.test(`${title} ${detail}`);
}
function normalizeRunStatus(status) {
  const raw = String(status || "").trim().toLowerCase();
  if (raw === "streaming") return "running";
  if (raw === "awaiting") return "awaiting";
  if (raw === "done") return "completed";
  if (raw === "error") return "failed";
  return raw || "running";
}
function RunPanel() {
  const { state, dispatch, openFile } = useApp();
  const [configs, setConfigs] = reactExports.useState(loadConfigs);
  const [showAdd, setShowAdd] = reactExports.useState(false);
  const [showPresets, setShowPresets] = reactExports.useState(false);
  const [newName, setNewName] = reactExports.useState("");
  const [newCmd, setNewCmd] = reactExports.useState("");
  const [newCwd, setNewCwd] = reactExports.useState("");
  const [diffPreviewPath, setDiffPreviewPath] = reactExports.useState("");
  const [running, setRunning] = reactExports.useState(null);
  const activityFeed = Array.isArray(state.activityFeed) ? state.activityFeed : [];
  const persist = (next) => {
    setConfigs(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };
  const addConfig = () => {
    if (!newCmd.trim()) return;
    const cfg = {
      id: Date.now().toString(36),
      name: newName.trim() || newCmd.trim(),
      command: newCmd.trim(),
      cwd: newCwd.trim() || state.projectRoot || "",
      icon: "▶"
    };
    persist([...configs, cfg]);
    setNewName("");
    setNewCmd("");
    setNewCwd("");
    setShowAdd(false);
  };
  const addPreset = (preset) => {
    const cfg = {
      id: Date.now().toString(36),
      name: preset.name,
      command: preset.command,
      cwd: state.projectRoot || "",
      icon: preset.icon
    };
    persist([...configs, cfg]);
    setShowPresets(false);
  };
  const deleteConfig = (id2) => persist(configs.filter((cfg) => cfg.id !== id2));
  const runConfig = reactExports.useCallback(async (cfg) => {
    setRunning(cfg.id);
    dispatch({ type: "SET_TERMINAL", open: true });
    await new Promise((resolve) => setTimeout(resolve, 150));
    window.dispatchEvent(new CustomEvent("kendr:run-command", {
      detail: { command: cfg.cwd ? `cd "${cfg.cwd}" && ${cfg.command}` : cfg.command }
    }));
    setTimeout(() => setRunning(null), 1500);
  }, [dispatch]);
  const openFolder = async (setter) => {
    const dir = await window.kendrAPI?.dialog.openDirectory();
    if (dir) setter(dir);
  };
  const openActivityItem = reactExports.useCallback(async (item) => {
    const filePath = String(item?.path || "").trim();
    if (!filePath) return;
    await openFile(filePath);
  }, [openFile]);
  const reviewActivityItem = reactExports.useCallback((item) => {
    const filePath = String(item?.path || "").trim();
    if (!filePath) return;
    setDiffPreviewPath(filePath);
  }, []);
  const activityItems = reactExports.useMemo(() => activityFeed.slice(0, 10), [activityFeed]);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      GitDiffPreview,
      {
        cwd: state.projectRoot,
        filePath: diffPreviewPath,
        onClose: () => setDiffPreviewPath(""),
        onOpenFile: (filePath) => openActivityItem({ path: filePath })
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-header", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-title", children: "Activity" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-header-actions", children: [
        !!activityItems.length && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-btn-sm", onClick: () => dispatch({ type: "CLEAR_ACTIVITY_FEED" }), children: "Clear" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-btn-sm", onClick: () => setShowPresets((value) => !value), children: "Templates" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-btn-sm rp-btn-sm--primary", onClick: () => setShowAdd((value) => !value), children: "+ Add" })
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-list", children: [
      activityItems.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-empty rp-empty--activity", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "No recent agent activity yet." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Start a run in Studio or Project mode and it will appear here." })
      ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "rp-activity-feed", children: activityItems.map((entry) => {
        const progress = Array.isArray(entry.progress) ? entry.progress.filter((item) => !isShellProgressItem(item)) : [];
        const cards = summarizeRunArtifacts(progress, entry.artifacts);
        const checklist = Array.isArray(entry.checklist) ? entry.checklist : [];
        const planLike = checklist.length > 0 && (entry.mode === "plan" || isPlanApprovalScope(entry.approvalScope, entry.approvalKind, entry.approvalRequest));
        const latestPath = cards.flatMap((card) => Array.isArray(card.items) ? card.items : []).find((item) => item?.path);
        const elapsedSeconds = entry.runStartedAt ? Math.max(0, Math.floor((Date.now() - new Date(entry.runStartedAt).getTime()) / 1e3)) : 0;
        return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-card", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-head", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-meta", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-activity-source", children: entry.source }),
              entry.modeLabel && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-activity-chip", children: entry.modeLabel }),
              entry.runId && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-activity-chip", children: entry.runId.slice(-8) })
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `rp-activity-status rp-activity-status--${normalizeRunStatus(entry.status)}`, children: normalizeRunStatus(entry.status) })
          ] }),
          !!cards.length && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-grid", children: cards.map((card) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `kc-activity-card kc-activity-card--${card.kind}`, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-activity-card-head", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-kind", children: card.kind }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-title", children: card.title })
              ] }),
              card.kind === "edit" && Array.isArray(card.items) && card.items.some((item) => item?.path) && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-action", onClick: () => reviewActivityItem(card.items.find((item) => item?.path)), children: "Review" })
            ] }),
            Array.isArray(card.items) && card.items.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-activity-card-items", children: card.items.slice(0, 3).map((item) => item?.path ? /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kc-activity-card-item kc-activity-card-item--action", onClick: () => openActivityItem(item), children: item.label }, `${entry.id}-${item.path}-${item.label}`) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-activity-card-item", children: item.label }, `${entry.id}-${item.label}`)) })
          ] }, `${entry.id}-${card.kind}-${card.title}`)) }),
          planLike && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-plan-preview", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "rp-plan-title", children: "Plan" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-list", children: checklist.slice(0, 4).map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-item", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-mark", children: item.done ? "✓" : item.status === "running" ? "…" : "·" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kc-checklist-body", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kc-checklist-row", children: [
                /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "kc-checklist-step", children: [
                  item.step,
                  "."
                ] }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "kc-checklist-text", children: item.title })
              ] }) })
            ] }, `${entry.id}-${item.step}-${item.title}`)) })
          ] }),
          entry.content && !planLike && !isSkillApproval(entry.approvalKind, entry.approvalRequest) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-content", children: [
            entry.content.slice(0, 240),
            entry.content.length > 240 ? "…" : ""
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-activity-footer", children: [
            entry.runId && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: formatDuration(elapsedSeconds) }),
            latestPath?.path && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-btn-sm", onClick: () => openActivityItem(latestPath), children: "Open file" })
          ] })
        ] }, entry.id);
      }) }),
      (showPresets || showAdd || configs.length > 0) && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-command-block", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "rp-section-title", children: "Commands" }),
        showPresets && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-presets", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "rp-presets-label", children: "Click to add preset" }),
          PRESETS.map((preset) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "rp-preset-item", onClick: () => addPreset(preset), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: preset.icon }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-preset-name", children: preset.name }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-preset-cmd", children: preset.command })
          ] }, preset.name))
        ] }),
        showAdd && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-add-form", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "rp-input", placeholder: "Name (optional)", value: newName, onChange: (event) => setNewName(event.target.value) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              className: "rp-input",
              placeholder: "Command  e.g. npm run dev",
              value: newCmd,
              onChange: (event) => setNewCmd(event.target.value),
              onKeyDown: (event) => event.key === "Enter" && addConfig()
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-dir-row", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "input",
              {
                className: "rp-input rp-input--flex",
                placeholder: "Working dir (optional, default: project root)",
                value: newCwd,
                onChange: (event) => setNewCwd(event.target.value)
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-icon-btn", onClick: () => openFolder(setNewCwd), children: "…" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-form-actions", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-add-confirm", onClick: addConfig, disabled: !newCmd.trim(), children: "Add" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-cancel", onClick: () => setShowAdd(false), children: "Cancel" })
          ] })
        ] }),
        !configs.length && !showAdd && !showPresets ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-empty rp-empty--commands", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "No run configurations yet." }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("p", { children: [
            "Click ",
            /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Templates" }),
            " or ",
            /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "+ Add" }),
            "."
          ] })
        ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "rp-config-list", children: configs.map((cfg) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `rp-config ${running === cfg.id ? "running" : ""}`, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: "rp-run-btn",
              onClick: () => runConfig(cfg),
              title: `Run: ${cfg.command}`,
              disabled: running === cfg.id,
              children: running === cfg.id ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-running-dot" }) : cfg.icon || "▶"
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rp-config-info", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-config-name", children: cfg.name }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rp-config-cmd", children: cfg.command }),
            cfg.cwd && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "rp-config-cwd", children: [
              "📁 ",
              cfg.cwd.split(/[\\/]/).slice(-2).join("/")
            ] })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "rp-del-btn", onClick: () => deleteConfig(cfg.id), title: "Remove", children: "✕" })
        ] }, cfg.id)) })
      ] })
    ] })
  ] });
}
function GitPanel() {
  const { state, dispatch } = useApp();
  const [files, setFiles] = reactExports.useState([]);
  const [staged, setStaged] = reactExports.useState([]);
  const [commits, setCommits] = reactExports.useState([]);
  const [message, setMessage] = reactExports.useState("");
  const [loading, setLoading] = reactExports.useState(false);
  const api = window.kendrAPI;
  const cwd = state.projectRoot;
  const refresh = reactExports.useCallback(async () => {
    if (!cwd || !api) return;
    setLoading(true);
    const [statusRes, logRes] = await Promise.all([
      api.git.status(cwd),
      api.git.log(cwd, 10)
    ]);
    if (!statusRes.error) {
      setFiles(statusRes.files || []);
      dispatch({ type: "SET_GIT_STATUS", status: statusRes.files, branch: statusRes.branch });
    }
    if (!logRes.error) setCommits(logRes.commits || []);
    setLoading(false);
  }, [cwd]);
  reactExports.useEffect(() => {
    refresh();
  }, [cwd]);
  const stageFile = async (f2) => {
    await api?.git.stage(cwd, [`"${f2.path}"`]);
    setStaged((s) => [...s.filter((x2) => x2 !== f2.path), f2.path]);
    refresh();
  };
  const stageAll = async () => {
    await api?.git.stage(cwd, ["."]);
    refresh();
  };
  const commit = async () => {
    if (!message.trim()) return;
    setLoading(true);
    const res = await api?.git.commit(cwd, message);
    if (!res?.error) {
      setMessage("");
      refresh();
    } else alert(res.error);
    setLoading(false);
  };
  const push = async () => {
    setLoading(true);
    const res = await api?.git.push(cwd);
    if (res?.error) alert(res.error);
    setLoading(false);
  };
  const pull = async () => {
    setLoading(true);
    const res = await api?.git.pull(cwd);
    if (res?.error) alert(res.error);
    refresh();
    setLoading(false);
  };
  const statusColor = (s) => {
    if (s === "M") return "#e3b341";
    if (s === "A" || s === "?") return "#89d185";
    if (s === "D") return "#f47067";
    return "#cccccc";
  };
  if (!cwd) return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sidebar-empty", children: "Open a project folder to see Git status" });
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "git-panel", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "git-actions", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "icon-btn", title: "Refresh", onClick: refresh, children: "⟳" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "icon-btn", title: "Pull", onClick: pull, children: "↓" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "icon-btn", title: "Push", onClick: push, children: "↑" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "git-section", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "git-section-header", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
          "CHANGES (",
          files.length,
          ")"
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "icon-btn", title: "Stage all", onClick: stageAll, children: "+" })
      ] }),
      files.map((f2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "git-file", onClick: () => stageFile(f2), children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "git-file-status", style: { color: statusColor(f2.status) }, children: f2.status }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "git-file-name", children: f2.path })
      ] }, f2.path)),
      files.length === 0 && !loading && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "git-clean", children: "No changes" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "git-commit", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "textarea",
        {
          className: "git-commit-input",
          placeholder: "Commit message…",
          value: message,
          onChange: (e) => setMessage(e.target.value),
          rows: 3
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: "btn-primary btn-full",
          disabled: !message.trim() || loading,
          onClick: commit,
          children: "Commit"
        }
      )
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "git-section", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "git-section-header", children: "RECENT COMMITS" }),
      commits.map((c) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "git-commit-item", title: c.hash, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "git-commit-hash", children: c.hash?.slice(0, 7) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "git-commit-msg", children: c.subject }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "git-commit-date", children: c.date })
      ] }, c.hash))
    ] })
  ] });
}
function ProjectWorkspace() {
  const { state, dispatch, openFile } = useApp();
  const editorInstanceRef = reactExports.useRef(null);
  const [leftW, setLeftW] = reactExports.useState(240);
  const [rightW, setRightW] = reactExports.useState(360);
  const [bottomH, setBottomH] = reactExports.useState(240);
  const [showBottom, setShowBottom] = reactExports.useState(false);
  const [bottomTab, setBottomTab] = reactExports.useState("terminal");
  const [leftTab, setLeftTab] = reactExports.useState("files");
  const [inlineEdit, setInlineEdit] = reactExports.useState(null);
  const inlineInputRef = reactExports.useRef(null);
  const dragging = reactExports.useRef(null);
  const onDividerMouseDown = reactExports.useCallback((which, e) => {
    e.preventDefault();
    dragging.current = { which, startX: e.clientX, startY: e.clientY, startLeft: leftW, startRight: rightW, startBottom: bottomH };
    const onMove = (ev) => {
      if (!dragging.current) return;
      const d = dragging.current;
      if (d.which === "left") setLeftW(Math.max(180, Math.min(480, d.startLeft + (ev.clientX - d.startX))));
      else if (d.which === "right") setRightW(Math.max(280, Math.min(640, d.startRight - (ev.clientX - d.startX))));
      else setBottomH(Math.max(80, Math.min(560, d.startBottom - (ev.clientY - d.startY))));
    };
    const onUp = () => {
      dragging.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [leftW, rightW, bottomH]);
  reactExports.useEffect(() => {
    const handler = (e) => {
      setInlineEdit({ top: e.detail?.top ?? 80, path: e.detail?.path, selectedText: e.detail?.selectedText || "" });
      setTimeout(() => inlineInputRef.current?.focus(), 60);
      if (!state.composerOpen) dispatch({ type: "TOGGLE_COMPOSER" });
      window.dispatchEvent(new CustomEvent("kendr:composer-set-mode", { detail: "edit" }));
    };
    window.addEventListener("kendr:inline-edit", handler);
    return () => window.removeEventListener("kendr:inline-edit", handler);
  }, [state.composerOpen, dispatch]);
  reactExports.useEffect(() => {
    const handler = () => {
      if (!state.composerOpen) dispatch({ type: "TOGGLE_COMPOSER" });
      window.dispatchEvent(new CustomEvent("kendr:composer-set-mode", { detail: "edit" }));
    };
    window.addEventListener("kendr:composer-edit", handler);
    return () => window.removeEventListener("kendr:composer-edit", handler);
  }, [state.composerOpen, dispatch]);
  reactExports.useEffect(() => {
    const openTerminal = () => {
      setBottomTab("terminal");
      setShowBottom(true);
    };
    const openRun = () => {
      setBottomTab("run");
      setShowBottom(true);
    };
    window.addEventListener("kendr:open-terminal", openTerminal);
    window.addEventListener("kendr:open-run-panel", openRun);
    return () => {
      window.removeEventListener("kendr:open-terminal", openTerminal);
      window.removeEventListener("kendr:open-run-panel", openRun);
    };
  }, []);
  reactExports.useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "F") {
        e.preventDefault();
        setLeftTab("search");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const toggleBottom = (tab) => {
    if (showBottom && bottomTab === tab) setShowBottom(false);
    else {
      setBottomTab(tab);
      setShowBottom(true);
    }
  };
  const submitInlineEdit = () => {
    const instruction = inlineInputRef.current?.value?.trim();
    if (!instruction) {
      setInlineEdit(null);
      return;
    }
    window.dispatchEvent(new CustomEvent("kendr:inline-edit-submit", { detail: { instruction, path: inlineEdit?.path, selectedText: inlineEdit?.selectedText } }));
    setInlineEdit(null);
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-main", style: { bottom: showBottom ? bottomH + 1 : 0 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-left", style: { width: leftW }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-left-tabs", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `pw-left-tab ${leftTab === "files" ? "active" : ""}`, onClick: () => setLeftTab("files"), title: "Explorer (Ctrl+Shift+E)", children: /* @__PURE__ */ jsxRuntimeExports.jsx(FilesTabIcon, {}) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `pw-left-tab ${leftTab === "search" ? "active" : ""}`, onClick: () => setLeftTab("search"), title: "Search (Ctrl+Shift+F)", children: /* @__PURE__ */ jsxRuntimeExports.jsx(SearchTabIcon, {}) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `pw-left-tab ${leftTab === "git" ? "active" : ""}`, onClick: () => setLeftTab("git"), title: "Source Control", children: /* @__PURE__ */ jsxRuntimeExports.jsx(GitTabIcon, {}) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `pw-left-tab ${leftTab === "runs" ? "active" : ""}`, onClick: () => setLeftTab("runs"), title: "Runs & Orchestration", children: /* @__PURE__ */ jsxRuntimeExports.jsx(RunsTabIcon, {}) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-left-tab-spacer" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: `pw-left-tab pw-left-tab--bottom ${leftTab === "extensions" ? "active" : ""}`,
              onClick: () => setLeftTab(leftTab === "extensions" ? "files" : "extensions"),
              title: "Agents, MCP & Skills",
              children: /* @__PURE__ */ jsxRuntimeExports.jsx(ExtensionsTabIcon, {})
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: `pw-left-tab pw-left-tab--bottom ${leftTab === "settings" ? "active" : ""}`,
              onClick: () => setLeftTab(leftTab === "settings" ? "files" : "settings"),
              title: "Settings",
              children: /* @__PURE__ */ jsxRuntimeExports.jsx(SettingsTabIcon, {})
            }
          )
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-left-body", children: [
          leftTab === "files" && /* @__PURE__ */ jsxRuntimeExports.jsx(FileExplorer, {}),
          leftTab === "search" && /* @__PURE__ */ jsxRuntimeExports.jsx(SearchPanel, { projectRoot: state.projectRoot, onOpenFile: openFile }),
          leftTab === "git" && /* @__PURE__ */ jsxRuntimeExports.jsx(GitPanel, {}),
          leftTab === "runs" && /* @__PURE__ */ jsxRuntimeExports.jsx(AgentOrchestration, {}),
          leftTab === "extensions" && /* @__PURE__ */ jsxRuntimeExports.jsx(ExtensionsPanel, { onNavigate: (view) => dispatch({ type: "SET_VIEW", view }) }),
          leftTab === "settings" && /* @__PURE__ */ jsxRuntimeExports.jsx(SettingsSidebar, { onNavigate: (view) => dispatch({ type: "SET_VIEW", view }) })
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-divider-v", onMouseDown: (e) => onDividerMouseDown("left", e) }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-center", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-center-toolbar", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(TabBar, {}),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-toolbar-actions", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `pw-tool-btn ${showBottom && bottomTab === "terminal" ? "active" : ""}`, title: "Terminal (Ctrl+`)", onClick: () => toggleBottom("terminal"), children: /* @__PURE__ */ jsxRuntimeExports.jsx(TermIcon, {}) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `pw-tool-btn ${showBottom && bottomTab === "run" ? "active" : ""}`, title: "Activity Panel", onClick: () => toggleBottom("run"), children: /* @__PURE__ */ jsxRuntimeExports.jsx(RunIcon, {}) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `pw-tool-btn ${state.composerOpen ? "active" : ""}`, title: "Workflow Panel (Ctrl+Shift+A)", onClick: () => dispatch({ type: "TOGGLE_COMPOSER" }), children: /* @__PURE__ */ jsxRuntimeExports.jsx(ComposerIcon, {}) })
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-editor-area", style: { position: "relative" }, children: [
          state.openTabs.length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx(EditorPanel, { onEditorMount: (ed2) => {
            editorInstanceRef.current = ed2;
          } }) : /* @__PURE__ */ jsxRuntimeExports.jsx(ProjectWelcome, { onOpenTerminal: () => toggleBottom("terminal"), onOpenRun: () => toggleBottom("run") }),
          inlineEdit && /* @__PURE__ */ jsxRuntimeExports.jsxs(
            "div",
            {
              className: "ile-widget",
              style: { top: Math.min(inlineEdit.top, 400) + "px" },
              children: [
                inlineEdit.selectedText && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ile-preview", children: [
                  inlineEdit.selectedText.split("\n").slice(0, 3).join("\n"),
                  inlineEdit.selectedText.split("\n").length > 3 ? "\n…" : ""
                ] }),
                /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ile-row", children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ile-icon", children: "✨" }),
                  /* @__PURE__ */ jsxRuntimeExports.jsx(
                    "input",
                    {
                      ref: inlineInputRef,
                      className: "ile-input",
                      placeholder: "Edit with AI… (Enter to apply, Esc to cancel)",
                      onKeyDown: (e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          submitInlineEdit();
                        }
                        if (e.key === "Escape") setInlineEdit(null);
                      }
                    }
                  ),
                  /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ile-submit", onClick: submitInlineEdit, children: "↩" }),
                  /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ile-cancel", onClick: () => setInlineEdit(null), children: "✕" })
                ] })
              ]
            }
          )
        ] })
      ] }),
      state.composerOpen && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-divider-v", onMouseDown: (e) => onDividerMouseDown("right", e) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-right", style: { width: rightW }, children: /* @__PURE__ */ jsxRuntimeExports.jsx(AIComposer, { editorInstanceRef }) })
      ] })
    ] }),
    showBottom && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-divider-h", style: { bottom: bottomH }, onMouseDown: (e) => onDividerMouseDown("bottom", e) }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-bottom", style: { height: bottomH }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-bottom-header", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `pw-bottom-tab ${bottomTab === "terminal" ? "active" : ""}`, onClick: () => setBottomTab("terminal"), children: "Terminal" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `pw-bottom-tab ${bottomTab === "run" ? "active" : ""}`, onClick: () => setBottomTab("run"), children: "Activity" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-bottom-spacer" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pw-bottom-close", onClick: () => setShowBottom(false), children: "✕" })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-bottom-body", children: [
          bottomTab === "terminal" && /* @__PURE__ */ jsxRuntimeExports.jsx(TerminalPanel, {}),
          bottomTab === "run" && /* @__PURE__ */ jsxRuntimeExports.jsx(RunPanel, {})
        ] })
      ] })
    ] })
  ] });
}
function SearchPanel({ projectRoot, onOpenFile }) {
  const [query, setQuery] = reactExports.useState("");
  const [results, setResults] = reactExports.useState([]);
  const [searching, setSearching] = reactExports.useState(false);
  const base = window.__kendrBackendUrl || "http://127.0.0.1:2151";
  const search = reactExports.useCallback(async (q2) => {
    if (!q2.trim()) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const r2 = await fetch(`${base}/api/files/search?q=${encodeURIComponent(q2)}&root=${encodeURIComponent(projectRoot || "")}`);
      if (r2.ok) {
        const data = await r2.json();
        setResults(data.results || data.matches || []);
      } else {
        setResults([]);
      }
    } catch {
      setResults([]);
    }
    setSearching(false);
  }, [base, projectRoot]);
  reactExports.useEffect(() => {
    const t2 = setTimeout(() => {
      if (query) search(query);
    }, 350);
    return () => clearTimeout(t2);
  }, [query, search]);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-search-panel", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-search-header", children: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-search-title", children: "SEARCH" }) }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-search-input-row", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "input",
        {
          className: "pw-search-input",
          placeholder: "Search files… (Ctrl+Shift+F)",
          value: query,
          onChange: (e) => {
            setQuery(e.target.value);
            if (!e.target.value) setResults([]);
          }
        }
      ),
      query && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pw-search-clear", onClick: () => {
        setQuery("");
        setResults([]);
      }, children: "✕" })
    ] }),
    searching && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-search-status", children: "Searching…" }),
    !searching && results.length === 0 && query && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-search-status", children: [
      'No results for "',
      query,
      '"'
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-search-results", children: results.map((r2, i) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "pw-search-result", onClick: () => onOpenFile(r2.path || r2.file), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-search-result-file", children: (r2.file || r2.path || "").split(/[\\/]/).pop() }),
      r2.line && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pw-search-result-line", children: [
        ":",
        r2.line
      ] }),
      r2.text && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-search-result-text", children: (r2.text || "").trim().slice(0, 60) })
    ] }, i)) })
  ] });
}
function ProjectWelcome({ onOpenTerminal, onOpenRun }) {
  const { state, dispatch } = useApp();
  const quickActions = [
    { label: "Open File", icon: "📄", action: () => dispatch({ type: "SET_VIEW", view: "files" }) },
    { label: "Terminal", icon: "⌨", action: onOpenTerminal },
    { label: "Run Project", icon: "▶", action: onOpenRun },
    { label: "Agent Panel", icon: "✨", action: () => dispatch({ type: "TOGGLE_COMPOSER" }) }
  ];
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-welcome", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-welcome-logo", children: "⚡" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("h1", { className: "pw-welcome-name", children: state.projectRoot ? state.projectRoot.split(/[\\/]/).pop() : "Kendr" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "pw-welcome-path", children: state.projectRoot || "No project folder open" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-welcome-grid", children: quickActions.map((a) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "pw-welcome-card", onClick: a.action, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-welcome-card-icon", children: a.icon }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-welcome-card-label", children: a.label })
    ] }, a.label)) }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-welcome-tips", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pw-tip", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("kbd", { children: "Ctrl+K" }),
        " Edit with AI"
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pw-tip", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("kbd", { children: "Ctrl+Shift+F" }),
        " Search"
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pw-tip", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("kbd", { children: "Ctrl+`" }),
        " Terminal"
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pw-tip", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("kbd", { children: "Ctrl+Shift+P" }),
        " Commands"
      ] })
    ] })
  ] });
}
function ExtensionsPanel({ onNavigate }) {
  const ITEMS = [
    { id: "agents", icon: "🤖", label: "Agents & Capabilities", desc: "Manage kendr agents and their tools" },
    { id: "mcp", icon: "🔌", label: "MCP Servers", desc: "Model Context Protocol integrations" },
    { id: "skills", icon: "⭐", label: "Skills", desc: "Intent-based skill routing" },
    { id: "models", icon: "🗄", label: "Model Manager", desc: "Pull and manage Ollama models" },
    { id: "runs", icon: "⏱", label: "Runs & Orchestration", desc: "View active and past runs" }
  ];
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-ext-panel", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-section-label", children: "EXTENSIONS" }),
    ITEMS.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "pw-ext-item", onClick: () => onNavigate(item.id), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-icon", children: item.icon }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-ext-info", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-name", children: item.label }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-desc", children: item.desc })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-arrow", children: "›" })
    ] }, item.id))
  ] });
}
function SettingsSidebar({ onNavigate }) {
  const { state } = useApp();
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-ext-panel", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pw-section-label", children: "SETTINGS" }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "pw-ext-item", onClick: () => onNavigate("settings"), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-icon", children: "⚙️" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-ext-info", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-name", children: "Preferences" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-desc", children: "API keys, backend, UI options" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-arrow", children: "›" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: "pw-ext-item", onClick: () => onNavigate("models"), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-icon", children: "🗄" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-ext-info", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-name", children: "Model Manager" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-desc", children: "Pull and switch Ollama models" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-arrow", children: "›" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-ext-info-block", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-ext-kv", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Backend" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `pw-ext-badge ${state.backendStatus === "running" ? "ok" : "err"}`, children: state.backendStatus })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pw-ext-kv", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Project" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pw-ext-val", children: state.projectRoot ? state.projectRoot.split(/[\\/]/).pop() : "—" })
      ] })
    ] })
  ] });
}
function FilesTabIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("polyline", { points: "13 2 13 9 20 9" })
  ] });
}
function SearchTabIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "11", cy: "11", r: "8" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("line", { x1: "21", y1: "21", x2: "16.65", y2: "16.65" })
  ] });
}
function GitTabIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "18", cy: "18", r: "3" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "6", cy: "6", r: "3" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "6", cy: "18", r: "3" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M18 9V7a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v8m12 0v2" })
  ] });
}
function RunsTabIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "12", cy: "12", r: "10" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("polyline", { points: "12 6 12 12 16 14" })
  ] });
}
function ExtensionsTabIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("rect", { x: "2", y: "3", width: "20", height: "14", rx: "2" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M8 21h8m-4-4v4" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "8", cy: "10", r: "1.5", fill: "currentColor" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "12", cy: "10", r: "1.5", fill: "currentColor" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "16", cy: "10", r: "1.5", fill: "currentColor" })
  ] });
}
function SettingsTabIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("circle", { cx: "12", cy: "12", r: "3" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" })
  ] });
}
function TermIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("polyline", { points: "4 17 10 11 4 5" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("line", { x1: "12", y1: "19", x2: "20", y2: "19" })
  ] });
}
function RunIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: /* @__PURE__ */ jsxRuntimeExports.jsx("polygon", { points: "5 3 19 12 5 21 5 3" }) });
}
function ComposerIcon() {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M12 2L2 7l10 5 10-5-10-5z" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M2 17l10 5 10-5" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("path", { d: "M2 12l10 5 10-5" })
  ] });
}
const TYPE_ICONS = { skill: "⚡", mcp_server: "🔌", api: "🌐", agent: "🤖", tool: "🔧" };
const STATUS_CLS = { active: "ok", verified: "info", draft: "warn", disabled: "muted", error: "err", deprecated: "muted" };
const TYPES = ["all", "agent", "skill", "mcp_server", "api", "tool"];
const STATUSES = ["all", "active", "verified", "draft", "disabled", "error"];
function AgentsPanel() {
  const { state } = useApp();
  const base = state.backendUrl || "http://127.0.0.1:2151";
  const [caps, setCaps] = reactExports.useState([]);
  const [agents, setAgents] = reactExports.useState([]);
  const [loading, setLoading] = reactExports.useState(true);
  const [tab, setTab] = reactExports.useState("capabilities");
  const [typeFilter, setTypeFilter] = reactExports.useState("all");
  const [statusFilter, setStatusFilter] = reactExports.useState("all");
  const [search, setSearch] = reactExports.useState("");
  const [selected, setSelected] = reactExports.useState(null);
  const [err, setErr] = reactExports.useState(null);
  const [discovery, setDiscovery] = reactExports.useState(null);
  const loadCaps = reactExports.useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (typeFilter !== "all") params.set("type", typeFilter);
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (search.trim()) params.set("q", search.trim());
      const r2 = await fetch(`${base}/api/capabilities?${params}`);
      const data = await r2.json();
      setCaps(Array.isArray(data) ? data : data.capabilities || data.items || []);
    } catch (e) {
      setErr(e.message);
    }
  }, [base, typeFilter, statusFilter, search]);
  const loadAgents = reactExports.useCallback(async () => {
    try {
      const r2 = await fetch(`${base}/api/capabilities?type=agent&status=active`);
      const data = await r2.json();
      setAgents(Array.isArray(data) ? data : data.capabilities || []);
    } catch {
    }
  }, [base]);
  const loadDiscovery = reactExports.useCallback(async () => {
    try {
      const r2 = await fetch(`${base}/api/capabilities/discovery/cards`);
      const data = await r2.json();
      setDiscovery(data);
    } catch {
    }
  }, [base]);
  reactExports.useEffect(() => {
    setLoading(true);
    Promise.all([loadCaps(), loadAgents()]).finally(() => setLoading(false));
  }, [loadCaps, loadAgents]);
  reactExports.useEffect(() => {
    if (tab === "discovery" && !discovery) loadDiscovery();
  }, [tab, discovery, loadDiscovery]);
  const publishCap = async (id2) => {
    await fetch(`${base}/api/capabilities/${id2}/publish`, { method: "POST" });
    loadCaps();
  };
  const disableCap = async (id2) => {
    await fetch(`${base}/api/capabilities/${id2}/disable`, { method: "POST" });
    loadCaps();
  };
  const filteredCaps = caps.filter((c) => {
    if (search.trim()) {
      const q2 = search.toLowerCase();
      return (c.name || "").toLowerCase().includes(q2) || (c.description || "").toLowerCase().includes(q2);
    }
    return true;
  });
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-topbar", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-topbar-left", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-page-title", children: "Agents & Capabilities" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-page-sub", children: "Manage agents, tools, APIs, and all registered capabilities" })
    ] }) }),
    err && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-error-banner", children: [
      "⚠ ",
      err,
      " ",
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: () => setErr(null), children: "✕" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-tabs", children: [["capabilities", "Capabilities"], ["agents", "Active Agents"], ["discovery", "Discovery Cards"]].map(([id2, label]) => /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        className: `pp-tab ${tab === id2 ? "active" : ""}`,
        onClick: () => setTab(id2),
        children: label
      },
      id2
    )) }),
    tab === "capabilities" && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-filters", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "input",
          {
            className: "pp-search",
            placeholder: "Search capabilities…",
            value: search,
            onChange: (e) => setSearch(e.target.value)
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("select", { className: "pp-select pp-select--sm", value: typeFilter, onChange: (e) => setTypeFilter(e.target.value), children: TYPES.map((t2) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: t2, children: t2 === "all" ? "All types" : t2 }, t2)) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("select", { className: "pp-select pp-select--sm", value: statusFilter, onChange: (e) => setStatusFilter(e.target.value), children: STATUSES.map((s) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: s, children: s === "all" ? "All statuses" : s }, s)) })
      ] }),
      loading ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-loading", children: "Loading capabilities…" }) : filteredCaps.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-empty", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-icon", children: "🤖" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-title", children: "No capabilities found" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-sub", children: "Capabilities are auto-discovered from agents, MCP servers, and API integrations." })
      ] }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-cap-layout", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-cap-list", children: filteredCaps.map((c) => /* @__PURE__ */ jsxRuntimeExports.jsxs(
          "div",
          {
            className: `pp-cap-row ${selected?.capability_id === c.capability_id ? "selected" : ""}`,
            onClick: () => setSelected(c),
            children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-cap-icon", children: TYPE_ICONS[c.type] || "📦" }),
              /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-cap-row-info", children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-cap-row-name", children: c.name }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-cap-row-key", children: c.capability_key })
              ] }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `pp-badge pp-badge--${STATUS_CLS[c.status] || "muted"}`, children: c.status }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-cap-row-type", children: c.type })
            ]
          },
          c.capability_id
        )) }),
        selected ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-cap-detail", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-detail-header", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-detail-icon", children: TYPE_ICONS[selected.type] || "📦" }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-detail-name", children: selected.name }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-detail-key", children: selected.capability_key })
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `pp-badge pp-badge--${STATUS_CLS[selected.status] || "muted"}`, children: selected.status })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-detail-desc", children: selected.description || "No description." }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-detail-meta", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx(MetaRow, { label: "Type", value: selected.type }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(MetaRow, { label: "Version", value: selected.version }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(MetaRow, { label: "Visibility", value: selected.visibility }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(MetaRow, { label: "Health", value: selected.health_status || "—" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(MetaRow, { label: "Owner", value: selected.owner_user_id || "—" })
          ] }),
          selected.tags_json && (() => {
            try {
              const tags = JSON.parse(selected.tags_json);
              return tags.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-detail-tags", children: tags.map((t2) => /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-tool-chip", children: t2 }, t2)) }) : null;
            } catch {
              return null;
            }
          })(),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-detail-actions", children: [
            selected.status === "draft" && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--primary", onClick: () => publishCap(selected.capability_id), children: "Publish" }),
            selected.status === "active" && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--danger", onClick: () => disableCap(selected.capability_id), children: "Disable" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", onClick: () => setSelected(null), children: "Close" })
          ] })
        ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-cap-detail pp-cap-detail--empty", children: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Select a capability to view details" }) })
      ] })
    ] }),
    tab === "agents" && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-agents-grid", children: agents.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-empty", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-icon", children: "🤖" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-title", children: "No active agents" })
    ] }) : agents.map((a) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-agent-card", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-agent-card-icon", children: "🤖" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-agent-card-name", children: a.name }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-agent-card-desc", children: (a.description || "").slice(0, 100) }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-agent-card-footer", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `pp-badge pp-badge--${STATUS_CLS[a.status] || "muted"}`, children: a.status }),
        a.tags_json && (() => {
          try {
            return JSON.parse(a.tags_json).slice(0, 3).map((t2) => /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-tool-chip pp-tool-chip--sm", children: t2 }, t2));
          } catch {
            return null;
          }
        })()
      ] })
    ] }, a.capability_id)) }),
    tab === "discovery" && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-discovery", children: !discovery ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-loading", children: "Loading discovery cards…" }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-agents-grid", children: (Array.isArray(discovery) ? discovery : discovery.cards || []).map((card, i) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `pp-agent-card ${card.is_active === false ? "pp-agent-card--inactive" : ""}`, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-agent-card-icon", children: card.is_active ? "✅" : "⚙" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-agent-card-name", children: card.display_name || card.agent_name }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-agent-card-desc", children: (card.description || "").slice(0, 120) }),
      card.needs_config && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-agent-card-warn", children: [
        "⚠ Needs config: ",
        (card.missing_vars || []).join(", ")
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-agent-card-footer", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `pp-badge ${card.is_active ? "pp-badge--ok" : "pp-badge--warn"}`, children: card.is_active ? "active" : "inactive" }),
        card.category && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-tool-chip pp-tool-chip--sm", children: card.category })
      ] })
    ] }, i)) }) })
  ] });
}
function MetaRow({ label, value }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-meta-row", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-meta-label", children: label }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-meta-value", children: value })
  ] });
}
const EMPTY_ASSISTANT = {
  assistant_id: "",
  name: "",
  description: "",
  goal: "",
  system_prompt: "",
  model_provider: "",
  model_name: "",
  routing_policy: "balanced",
  status: "draft",
  attached_capabilities: [],
  memory_config: { summary: "", local_paths: [] }
};
const ROUTING_OPTIONS = [
  { id: "balanced", label: "Balanced" },
  { id: "quality", label: "Highest quality" },
  { id: "cost", label: "Lowest cost" },
  { id: "private", label: "Private first" }
];
function AssistantBuilder() {
  const { state, dispatch } = useApp();
  const base = state.backendUrl || "http://127.0.0.1:2151";
  const [assistants, setAssistants] = reactExports.useState([]);
  const [capabilities, setCapabilities] = reactExports.useState([]);
  const [selectedId, setSelectedId] = reactExports.useState("");
  const [draft, setDraft] = reactExports.useState(EMPTY_ASSISTANT);
  const [loading, setLoading] = reactExports.useState(true);
  const [saving, setSaving] = reactExports.useState(false);
  const [testing, setTesting] = reactExports.useState(false);
  const [error, setError] = reactExports.useState("");
  const [testMessage, setTestMessage] = reactExports.useState("Give me a short explanation of what you can do and how you would approach a task.");
  const [testResult, setTestResult] = reactExports.useState(null);
  const selectedAssistant = reactExports.useMemo(
    () => assistants.find((item) => item.assistant_id === selectedId) || null,
    [assistants, selectedId]
  );
  const load = reactExports.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [assistantRes, capRes] = await Promise.all([
        fetch(`${base}/api/assistants`),
        fetch(`${base}/api/capabilities?status=active`)
      ]);
      const assistantData = await assistantRes.json();
      const capData = await capRes.json();
      const nextAssistants = Array.isArray(assistantData.assistants) ? assistantData.assistants : [];
      const nextCaps = Array.isArray(capData) ? capData : capData.capabilities || capData.items || [];
      setAssistants(nextAssistants);
      setCapabilities(nextCaps.filter((item) => ["skill", "agent", "tool", "api", "mcp_server"].includes(item.type)));
      if (!selectedId && nextAssistants[0]?.assistant_id) {
        setSelectedId(nextAssistants[0].assistant_id);
      }
      if (!selectedId && !nextAssistants.length) {
        setDraft(EMPTY_ASSISTANT);
      }
    } catch (e) {
      setError(e.message || "Failed to load assistant builder");
    } finally {
      setLoading(false);
    }
  }, [base, selectedId]);
  reactExports.useEffect(() => {
    load();
  }, [load]);
  reactExports.useEffect(() => {
    if (selectedAssistant) {
      setDraft({
        ...EMPTY_ASSISTANT,
        ...selectedAssistant,
        attached_capabilities: Array.isArray(selectedAssistant.attached_capabilities) ? selectedAssistant.attached_capabilities : [],
        memory_config: typeof selectedAssistant.memory_config === "object" && selectedAssistant.memory_config ? selectedAssistant.memory_config : { summary: "", local_paths: [] }
      });
      setTestResult(null);
    } else if (!selectedId) {
      setDraft(EMPTY_ASSISTANT);
      setTestResult(null);
    }
  }, [selectedAssistant, selectedId]);
  const setField = (key, value) => setDraft((prev) => ({ ...prev, [key]: value }));
  const setMemoryField = (key, value) => setDraft((prev) => ({ ...prev, memory_config: { ...prev.memory_config || {}, [key]: value } }));
  const resetNew = () => {
    setSelectedId("");
    setDraft(EMPTY_ASSISTANT);
    setTestResult(null);
    setError("");
  };
  const toggleCapability = (cap) => {
    setDraft((prev) => {
      const current = Array.isArray(prev.attached_capabilities) ? prev.attached_capabilities : [];
      const capabilityId = cap.capability_id || cap.id;
      const capabilityKey = cap.capability_key || cap.key;
      const exists = current.some((item) => item.capability_id === capabilityId);
      return {
        ...prev,
        attached_capabilities: exists ? current.filter((item) => item.capability_id !== capabilityId) : [
          ...current,
          {
            capability_id: capabilityId,
            capability_key: capabilityKey,
            name: cap.name,
            type: cap.type
          }
        ]
      };
    });
  };
  const saveAssistant = async (statusOverride = null) => {
    if (!draft.name.trim()) {
      setError("Assistant name is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload = {
        ...draft,
        status: statusOverride || draft.status || "draft"
      };
      const isUpdate = !!draft.assistant_id;
      const url = isUpdate ? `${base}/api/assistants/${draft.assistant_id}/update` : `${base}/api/assistants`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || res.statusText);
      await load();
      setSelectedId(data.assistant_id || data.id || payload.assistant_id || "");
      setDraft((prev) => ({ ...prev, ...data }));
    } catch (e) {
      setError(e.message || "Failed to save assistant");
    } finally {
      setSaving(false);
    }
  };
  const deleteAssistant = async () => {
    if (!draft.assistant_id) return;
    if (!window.confirm("Delete this assistant?")) return;
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${base}/api/assistants/${draft.assistant_id}/delete`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || res.statusText);
      resetNew();
      await load();
    } catch (e) {
      setError(e.message || "Failed to delete assistant");
    } finally {
      setSaving(false);
    }
  };
  const runTest = async () => {
    if (!draft.assistant_id) {
      setError("Save the assistant before testing it");
      return;
    }
    if (!testMessage.trim()) {
      setError("Test message is required");
      return;
    }
    setTesting(true);
    setError("");
    try {
      const res = await fetch(`${base}/api/assistants/${draft.assistant_id}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: testMessage })
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || res.statusText);
      setTestResult(data);
    } catch (e) {
      setError(e.message || "Assistant test failed");
    } finally {
      setTesting(false);
    }
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "assistant-builder", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "assistant-builder__sidebar surface-card", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "assistant-builder__sidebar-head", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("h3", { children: "Assistants" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Draft, test, and publish reusable AI workers." })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--ghost", onClick: resetNew, children: "New" })
      ] }),
      loading ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-loading", children: "Loading assistants…" }) : assistants.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "empty-state", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "empty-state__title", children: "No assistants yet" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "empty-state__body", children: "Create your first assistant from goal, instructions, and connected capabilities." })
      ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "assistant-list", children: assistants.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs(
        "button",
        {
          className: `assistant-list__item ${selectedId === item.assistant_id ? "active" : ""}`,
          onClick: () => setSelectedId(item.assistant_id),
          children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "assistant-list__name", children: item.name }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "assistant-list__meta", children: [
              item.status || "draft",
              " · ",
              item.routing_policy || "balanced"
            ] })
          ]
        },
        item.assistant_id
      )) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "assistant-builder__main", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "assistant-builder__header", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: draft.assistant_id ? "Assistant Builder" : "Create Assistant" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Define the assistant goal, add instructions, attach capabilities, and test it before you publish." })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "assistant-builder__actions", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--ghost", onClick: () => dispatch({ type: "SET_VIEW", view: "studio" }), children: "Open Studio" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--ghost", disabled: saving, onClick: () => saveAssistant("draft"), children: "Save Draft" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--primary", disabled: saving, onClick: () => saveAssistant("active"), children: "Publish" })
          ] })
        ] }),
        error && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-error-banner", children: [
          "⚠ ",
          error,
          " ",
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: () => setError(""), children: "✕" })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "assistant-form-grid", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Name" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", value: draft.name, onChange: (e) => setField("name", e.target.value), placeholder: "Customer Support Assistant" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Status" }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "pp-select", value: draft.status || "draft", onChange: (e) => setField("status", e.target.value), children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "draft", children: "Draft" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "active", children: "Active" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "paused", children: "Paused" })
            ] })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "assistant-form-grid__full", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Description" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", value: draft.description, onChange: (e) => setField("description", e.target.value), placeholder: "One-line product description for the assistant" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "assistant-form-grid__full", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Goal" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("textarea", { className: "pp-input assistant-textarea", value: draft.goal, onChange: (e) => setField("goal", e.target.value), placeholder: "What should this assistant actually do?" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "assistant-form-grid__full", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "System Instructions" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("textarea", { className: "pp-input assistant-textarea assistant-textarea--lg", value: draft.system_prompt, onChange: (e) => setField("system_prompt", e.target.value), placeholder: "Add domain rules, tone, approval guidance, and constraints." })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Model Provider" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", value: draft.model_provider || "", onChange: (e) => setField("model_provider", e.target.value), placeholder: "openai, anthropic, ollama…" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Model Name" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", value: draft.model_name || "", onChange: (e) => setField("model_name", e.target.value), placeholder: "Leave blank for routed default" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Routing Policy" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("select", { className: "pp-select", value: draft.routing_policy || "balanced", onChange: (e) => setField("routing_policy", e.target.value), children: ROUTING_OPTIONS.map((option) => /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: option.id, children: option.label }, option.id)) })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Memory Summary" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", value: draft.memory_config?.summary || "", onChange: (e) => setMemoryField("summary", e.target.value), placeholder: "What should it remember or retrieve?" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "assistant-form-grid__full", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Local Memory Paths" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("textarea", { className: "pp-input assistant-textarea", value: (draft.memory_config?.local_paths || []).join("\n"), onChange: (e) => setMemoryField("local_paths", e.target.value.split("\n").map((item) => item.trim()).filter(Boolean)), placeholder: "/docs\\n/data/help-center" })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "grid-two", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: "Attached Capabilities" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Select the skills, tools, APIs, and MCP sources this assistant can use." })
          ] }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "assistant-cap-grid", children: capabilities.slice(0, 24).map((cap) => {
            const capabilityId = cap.capability_id || cap.id;
            const capabilityKey = cap.capability_key || cap.key;
            const checked = (draft.attached_capabilities || []).some((item) => item.capability_id === capabilityId);
            return /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { className: `assistant-cap-card ${checked ? "active" : ""}`, onClick: () => toggleCapability(cap), children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "assistant-cap-card__type", children: cap.type }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "assistant-cap-card__name", children: cap.name }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "assistant-cap-card__key", children: capabilityKey })
            ] }, capabilityId);
          }) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: "Quick Test" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Run a direct test against the configured assistant before shipping it into Studio." })
          ] }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("textarea", { className: "pp-input assistant-textarea assistant-textarea--lg", value: testMessage, onChange: (e) => setTestMessage(e.target.value) }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "hero-actions", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--primary", disabled: testing || !draft.assistant_id, onClick: runTest, children: testing ? "Testing…" : "Run Test" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--ghost", disabled: saving || !draft.assistant_id, onClick: deleteAssistant, children: "Delete" })
          ] }),
          testResult && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "assistant-test-result", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-grid", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-pill status-pill--neutral", children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__label", children: "Provider" }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__value", children: testResult.provider })
              ] }),
              /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-pill status-pill--neutral", children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__label", children: "Model" }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__value", children: testResult.model })
              ] })
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "assistant-test-result__panel", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Assistant response" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { children: testResult.answer })
            ] })
          ] })
        ] })
      ] })
    ] })
  ] });
}
const TABS$3 = [
  { id: "assistants", label: "Assistants" },
  { id: "capabilities", label: "Capabilities" },
  { id: "skills", label: "Skills" },
  { id: "developer", label: "Developer Workspace" }
];
function BuildHub() {
  const [tab, setTab] = reactExports.useState("assistants");
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kendr-page", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card surface-card--tight", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: "Build" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Create assistants, refine skills, and drop into the developer workspace when you need full control." })
      ] }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kendr-tabs", children: TABS$3.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `kendr-tab ${tab === item.id ? "active" : ""}`, onClick: () => setTab(item.id), children: item.label }, item.id)) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "build-content", children: [
      tab === "assistants" && /* @__PURE__ */ jsxRuntimeExports.jsx(AssistantBuilder, {}),
      tab === "capabilities" && /* @__PURE__ */ jsxRuntimeExports.jsx(AgentsPanel, {}),
      tab === "skills" && /* @__PURE__ */ jsxRuntimeExports.jsx(SkillsPanel, {}),
      tab === "developer" && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "developer-frame", children: /* @__PURE__ */ jsxRuntimeExports.jsx(ProjectWorkspace, {}) })
    ] })
  ] });
}
function MCPPanel() {
  const { state } = useApp();
  const base = state.backendUrl || "http://127.0.0.1:2151";
  const [servers, setServers] = reactExports.useState([]);
  const [loading, setLoading] = reactExports.useState(true);
  const [showAdd, setShowAdd] = reactExports.useState(false);
  const [scaffold, setScaffold] = reactExports.useState("");
  const [showScaffold, setShowScaffold] = reactExports.useState(false);
  const [discovering, setDiscovering] = reactExports.useState(null);
  const [err, setErr] = reactExports.useState(null);
  const [form, setForm] = reactExports.useState({ name: "", connection: "", type: "http", description: "", auth_token: "" });
  const [configJson, setConfigJson] = reactExports.useState("");
  const getServerId = (srv) => srv?.id || srv?.server_id || "";
  const load = reactExports.useCallback(async () => {
    try {
      const r2 = await fetch(`${base}/api/mcp/servers`);
      if (!r2.ok) throw new Error(r2.statusText);
      const data = await r2.json();
      setServers(Array.isArray(data) ? data : data.servers || []);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [base]);
  reactExports.useEffect(() => {
    load();
  }, [load]);
  const addServer = async () => {
    try {
      const payload = configJson.trim() ? { config_json: configJson } : form;
      if (!configJson.trim() && (!form.name.trim() || !form.connection.trim())) return;
      const r2 = await fetch(`${base}/api/mcp/servers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await r2.json();
      if (!r2.ok || data.error) throw new Error(data.error || r2.statusText);
      setShowAdd(false);
      setForm({ name: "", connection: "", type: "http", description: "", auth_token: "" });
      setConfigJson("");
      load();
    } catch (e) {
      setErr(e.message);
    }
  };
  const removeServer = async (id2) => {
    const r2 = await fetch(`${base}/api/mcp/servers/${id2}/remove`, { method: "POST" });
    const data = await r2.json();
    if (!r2.ok || data.error) throw new Error(data.error || r2.statusText);
    load();
  };
  const toggleServer = async (id2, enabled) => {
    const r2 = await fetch(`${base}/api/mcp/servers/${id2}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !enabled })
    });
    const data = await r2.json();
    if (!r2.ok || data.error) throw new Error(data.error || r2.statusText);
    load();
  };
  const discoverTools = async (id2) => {
    setDiscovering(id2);
    try {
      const r2 = await fetch(`${base}/api/mcp/servers/${id2}/discover`, { method: "POST" });
      const data = await r2.json();
      if (!r2.ok || data.error) throw new Error(data.error || r2.statusText);
      load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setDiscovering(null);
    }
  };
  const loadScaffold = async () => {
    try {
      const r2 = await fetch(`${base}/api/mcp/scaffold`);
      const data = await r2.json();
      if (!r2.ok || data.error) throw new Error(data.error || r2.statusText);
      setScaffold(data.code || "");
      setShowScaffold(true);
    } catch (e) {
      setErr(e.message);
    }
  };
  const u2 = (k2) => (v2) => setForm((f2) => ({ ...f2, [k2]: v2 }));
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-topbar", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-topbar-left", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-page-title", children: "MCP Servers" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-page-sub", children: "Connect external tool servers to extend agent capabilities" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-topbar-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", onClick: loadScaffold, children: "View Scaffold" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--primary", onClick: () => setShowAdd((s) => !s), children: "+ Add Server" })
      ] })
    ] }),
    err && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-error-banner", children: [
      "⚠ ",
      err,
      " ",
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: () => setErr(null), children: "✕" })
    ] }),
    showAdd && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-add-card", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-add-title", children: "Add MCP Server" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-form-grid", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Name *" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", placeholder: "My Research Server", value: form.name, onChange: (e) => u2("name")(e.target.value) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Connection *" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", placeholder: "http://localhost:8000/mcp  or  python server.py", value: form.connection, onChange: (e) => u2("connection")(e.target.value) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Type" }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "pp-select", value: form.type, onChange: (e) => u2("type")(e.target.value), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "http", children: "HTTP / SSE" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "stdio", children: "Stdio (shell command)" })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Description" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", placeholder: "Optional description", value: form.description, onChange: (e) => u2("description")(e.target.value) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Auth Token" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", type: "password", placeholder: "Bearer token (optional)", value: form.auth_token, onChange: (e) => u2("auth_token")(e.target.value) })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-form-actions", style: { marginTop: 12, marginBottom: 8, justifyContent: "flex-start" }, children: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-form-label", style: { marginBottom: 0 }, children: "Or paste MCP JSON" }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "textarea",
        {
          className: "pp-input",
          rows: 10,
          placeholder: `{
  "mcpServers": {
    "aws-knowledge-mcp-server": {
      "url": "https://knowledge-mcp.global.api.aws",
      "type": "http",
      "disabled": false
    }
  }
}`,
          value: configJson,
          onChange: (e) => setConfigJson(e.target.value),
          style: { width: "100%", resize: "vertical", minHeight: 200 }
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-form-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--primary", onClick: addServer, disabled: !configJson.trim() && (!form.name.trim() || !form.connection.trim()), children: configJson.trim() ? "Import JSON" : "Add Server" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", onClick: () => setShowAdd(false), children: "Cancel" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-form-hint", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "HTTP:" }),
        " Kendr connects as an MCP client to the SSE endpoint.  ",
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Stdio:" }),
        " Kendr spawns the command and communicates via stdin/stdout."
      ] })
    ] }),
    showScaffold && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-modal-backdrop", onClick: () => setShowScaffold(false), children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-modal", onClick: (e) => e.stopPropagation(), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-modal-header", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "FastMCP Server Scaffold" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: () => setShowScaffold(false), children: "✕" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "pp-scaffold-code", children: scaffold || "Loading…" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-modal-footer", children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--primary", onClick: () => navigator.clipboard.writeText(scaffold), children: "Copy" }) })
    ] }) }),
    loading ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-loading", children: "Loading MCP servers…" }) : servers.length === 0 && !showAdd ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-empty", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-icon", children: "🔌" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-title", children: "No MCP servers connected" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-empty-sub", children: [
        "Add an MCP server to give your agents access to external tools. Click ",
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "View Scaffold" }),
        " to generate a FastMCP server template."
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--primary", style: { marginTop: 16 }, onClick: () => setShowAdd(true), children: "+ Add Your First Server" })
    ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-list", children: servers.map((srv) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `pp-card ${!srv.enabled ? "pp-card--disabled" : ""}`, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-card-top", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-card-icon", children: srv.type === "stdio" ? "⌨" : "🌐" }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-card-info", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-card-name", children: [
            srv.name,
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `pp-badge pp-badge--${srv.status || "unknown"}`, children: srv.status || "unknown" }),
            !srv.enabled && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-badge pp-badge--disabled", children: "disabled" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-card-conn", children: srv.connection }),
          srv.description && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-card-desc", children: srv.description }),
          srv.error && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-card-err", children: [
            "⚠ ",
            srv.error
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-card-meta", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-card-type", children: srv.type }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "pp-card-tools", children: [
            srv.tool_count ?? 0,
            " tools"
          ] }),
          srv.last_discovered && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-card-date", children: new Date(srv.last_discovered).toLocaleDateString() })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-card-actions", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: "pp-action-btn",
              onClick: () => discoverTools(getServerId(srv)),
              disabled: discovering === getServerId(srv),
              title: "Discover tools",
              children: discovering === getServerId(srv) ? "…" : "🔍"
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: `pp-action-btn ${srv.enabled ? "pp-action-btn--on" : ""}`,
              onClick: async () => {
                try {
                  await toggleServer(getServerId(srv), srv.enabled);
                } catch (e) {
                  setErr(e.message);
                }
              },
              title: srv.enabled ? "Disable" : "Enable",
              children: srv.enabled ? "●" : "○"
            }
          ),
          !srv.is_default && /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: "pp-action-btn pp-action-btn--danger",
              onClick: async () => {
                try {
                  await removeServer(getServerId(srv));
                } catch (e) {
                  setErr(e.message);
                }
              },
              title: "Remove",
              children: "✕"
            }
          )
        ] })
      ] }),
      Array.isArray(srv.tools) && srv.tools.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-tools", children: srv.tools.map((t2) => /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-tool-chip", title: t2.description, children: t2.name }, t2.name)) })
    ] }, getServerId(srv))) })
  ] });
}
const TABS$2 = [
  { id: "overview", label: "◎ Overview" },
  { id: "tool-sources", label: "🔌 MCP Servers" },
  { id: "skills", label: "⚡ Skills" },
  { id: "integrations", label: "🧩 Service Integrations" }
];
function IntegrationsHub() {
  const [tab, setTab] = reactExports.useState("overview");
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kendr-page", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card surface-card--tight", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: "Integrations" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Everything that extends what your agents can do — in one place." })
      ] }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kendr-tabs", children: TABS$2.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: `kendr-tab ${tab === item.id ? "active" : ""}`,
          onClick: () => setTab(item.id),
          children: item.label
        },
        item.id
      )) })
    ] }),
    tab === "overview" && /* @__PURE__ */ jsxRuntimeExports.jsx(ConnectorOverview, { onNavigate: setTab }),
    tab === "tool-sources" && /* @__PURE__ */ jsxRuntimeExports.jsx(MCPPanel, {}),
    tab === "skills" && /* @__PURE__ */ jsxRuntimeExports.jsx(SkillsPanel, {}),
    tab === "integrations" && /* @__PURE__ */ jsxRuntimeExports.jsx(IntegrationsPanel, {})
  ] });
}
function ConnectorOverview({ onNavigate }) {
  const { state } = useApp();
  const base = state.backendUrl || "http://127.0.0.1:2151";
  const [catalog, setCatalog] = reactExports.useState(null);
  const [loading, setLoading] = reactExports.useState(true);
  const [err, setErr] = reactExports.useState(null);
  const load = reactExports.useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const r2 = await fetch(`${base}/api/connectors`);
      if (!r2.ok) throw new Error(r2.statusText);
      setCatalog(await r2.json());
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [base]);
  reactExports.useEffect(() => {
    load();
  }, [load]);
  if (loading) return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-loading", children: "Loading connector catalog…" });
  if (err) return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-error-banner", children: [
    "⚠ ",
    err,
    " — Gateway may be offline.",
    /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: load, style: { marginLeft: 8 }, children: "Retry" })
  ] });
  const connectors = catalog?.connectors || [];
  const byType = catalog?.by_type || {};
  const skills = byType.skill || [];
  const mcpTools = byType.mcp_tool || [];
  const agents = byType.task_agent || [];
  const integrations = byType.integration || byType.plugin || [];
  const ready = connectors.filter((c) => c.status === "ready").length;
  const needsConfig = connectors.filter((c) => c.status === "needs_config").length;
  const total = connectors.length;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 20 }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }, children: [
      { label: "Total Connectors", value: total, color: "var(--text)", bg: "var(--bg-secondary)" },
      { label: "Ready", value: ready, color: "#27ae60", bg: "#27ae6010" },
      { label: "Needs Config", value: needsConfig, color: "#e6a700", bg: "#e6a70010" },
      { label: "Skills Installed", value: skills.filter((s) => s.status === "ready").length, color: "var(--accent)", bg: "var(--accent)10" }
    ].map(({ label, value, color, bg: bg2 }) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { background: bg2, border: "1px solid var(--border)", borderRadius: 10, padding: "14px 18px" }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 28, fontWeight: 700, color }, children: value }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", marginTop: 2 }, children: label })
    ] }, label)) }),
    [
      { key: "skill", items: skills, label: "⚡ Skills", tab: "skills", emptyAction: "Install skills to give agents reusable capabilities." },
      { key: "mcp_tool", items: mcpTools, label: "🔌 MCP Tools", tab: "tool-sources", emptyAction: "Add an MCP server to expose external tools to your agents." },
      { key: "integration", items: integrations, label: "🧩 Service Integrations", tab: "integrations", emptyAction: "Configure credentials in the Service Integrations tab." },
      { key: "task_agent", items: agents, label: "🤖 Built-in Agents", tab: null, emptyAction: null }
    ].map(({ key, items, label, tab, emptyAction }) => /* @__PURE__ */ jsxRuntimeExports.jsx(
      ConnectorSection,
      {
        label,
        items,
        emptyAction,
        onNavigate: tab ? () => onNavigate(tab) : null
      },
      key
    )),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { textAlign: "right", marginTop: 4 }, children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", onClick: load, style: { fontSize: 12 }, children: "↺ Refresh catalog" }) })
  ] });
}
function ConnectorSection({ label, items, emptyAction, onNavigate }) {
  const [expanded, setExpanded] = reactExports.useState(true);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 10, overflow: "visible" }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        style: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 16px", cursor: "pointer", userSelect: "none" },
        onClick: () => setExpanded((e) => !e),
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { style: { fontWeight: 600, fontSize: 14 }, children: [
            expanded ? "▾" : "▸",
            " ",
            label,
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { marginLeft: 8, fontSize: 12, fontWeight: 400, color: "var(--text-muted)" }, children: items.length })
          ] }),
          onNavigate && /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: "pp-btn pp-btn--ghost",
              style: { fontSize: 12 },
              onClick: (e) => {
                e.stopPropagation();
                onNavigate();
              },
              children: "Manage →"
            }
          )
        ]
      }
    ),
    expanded && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { borderTop: "1px solid var(--border)", padding: "12px 16px" }, children: items.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { fontSize: 13, color: "var(--text-muted)", padding: "4px 0" }, children: [
      emptyAction || "None configured.",
      onNavigate && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", style: { marginLeft: 10, fontSize: 12 }, onClick: onNavigate, children: "Set up →" })
    ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }, children: items.map((c) => /* @__PURE__ */ jsxRuntimeExports.jsx(ConnectorCard, { connector: c }, c.agent_name)) }) })
  ] });
}
function ConnectorCard({ connector: c }) {
  const [showDetails, setShowDetails] = reactExports.useState(false);
  const [popoverPos, setPopoverPos] = reactExports.useState({ top: 0, right: 0 });
  const btnRef = reactExports.useRef(null);
  const handleInfoClick = () => {
    if (!showDetails && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect();
      setPopoverPos({
        top: rect.bottom + 6,
        right: window.innerWidth - rect.right
      });
    }
    setShowDetails((v2) => !v2);
  };
  const statusColor = {
    ready: "#27ae60",
    needs_config: "#e6a700",
    not_discovered: "#888",
    disabled: "#888"
  }[c.status] || "#888";
  const statusLabel = {
    ready: "✓ Ready",
    needs_config: "⚙ Setup needed",
    not_discovered: "○ Not discovered",
    disabled: "— Disabled"
  }[c.status] || c.status;
  const compactDescription = String(c.description || "").replace(/\s+/g, " ").trim();
  const fullDescription = String(c.description || "").trim();
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card", style: {
    border: `1px solid ${c.status === "ready" ? "var(--border)" : "#e6a70044"}`
  }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-head", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 18 }, children: c.icon || "•" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ih-connector-card-title", children: c.display_name }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          ref: btnRef,
          className: "ih-connector-card-info-btn",
          title: "View full details",
          onClick: handleInfoClick,
          children: "i"
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "ih-connector-card-status", style: { color: statusColor }, children: statusLabel })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ih-connector-card-desc", title: compactDescription, children: compactDescription }),
    c.missing_config?.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-missing", children: [
      "Missing: ",
      c.missing_config.join(", ")
    ] }),
    c.required_inputs?.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-inputs", title: c.required_inputs.join(", "), children: [
      "inputs: ",
      c.required_inputs.join(", ")
    ] }),
    showDetails && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-popover", style: { top: popoverPos.top, right: popoverPos.right }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-popover-header", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: "Connector Details" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "ih-connector-card-popover-close", onClick: () => setShowDetails(false), children: "✕" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-popover-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Name:" }),
        " ",
        c.display_name || c.agent_name || "-"
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-popover-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Status:" }),
        " ",
        statusLabel
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-popover-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Type:" }),
        " ",
        c.type || "-"
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-popover-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Agent:" }),
        " ",
        c.agent_name || "-"
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-popover-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Description:" }),
        " ",
        fullDescription || "-"
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-popover-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Inputs:" }),
        " ",
        c.required_inputs?.length ? c.required_inputs.join(", ") : "-"
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ih-connector-card-popover-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "Missing Config:" }),
        " ",
        c.missing_config?.length ? c.missing_config.join(", ") : "-"
      ] })
    ] })
  ] });
}
function resolveSetupComponentId(integrationId) {
  const key = String(integrationId || "").trim().toLowerCase();
  const alias = {
    gmail: "google_workspace",
    google_drive: "google_workspace",
    microsoft_365: "microsoft_graph",
    microsoft365: "microsoft_graph",
    microsoft: "microsoft_graph"
  }[key];
  return alias || key;
}
function integrationIdFromConnector(integration) {
  const explicit = String(integration?.integration_id || integration?.id || "").trim();
  if (explicit) return explicit;
  const agentName = String(integration?.agent_name || "").trim();
  if (agentName.startsWith("integration:")) return agentName.slice("integration:".length);
  return "";
}
function IntegrationsPanel() {
  const { state, dispatch } = useApp();
  const base = state.backendUrl || "http://127.0.0.1:2151";
  const [integrations, setIntegrations] = reactExports.useState([]);
  const [loading, setLoading] = reactExports.useState(true);
  const [err, setErr] = reactExports.useState(null);
  const [providerKeys, setProviderKeys] = reactExports.useState({});
  const [keysSaved, setKeysSaved] = reactExports.useState(false);
  const [keysSaving, setKeysSaving] = reactExports.useState(false);
  const load = reactExports.useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const r2 = await fetch(`${base}/api/connectors`);
      if (!r2.ok) throw new Error(r2.statusText);
      const data = await r2.json();
      setIntegrations(data?.by_type?.integration || data?.by_type?.plugin || []);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [base]);
  reactExports.useEffect(() => {
    load();
  }, [load]);
  reactExports.useEffect(() => {
    setProviderKeys(state.settings || {});
  }, [state.settings]);
  const saveProviderKeys = async () => {
    const api = window.kendrAPI;
    if (!api?.settings) return;
    const providerSettingKeys = ["anthropicKey", "openaiKey", "openaiOrgId", "googleKey", "xaiKey"];
    const shouldRestartBackend = providerSettingKeys.some((key) => (state.settings?.[key] || "") !== (providerKeys?.[key] || ""));
    setKeysSaving(true);
    try {
      for (const [k2, v2] of Object.entries(providerKeys || {})) {
        if (typeof v2 === "string") await api.settings.set(k2, v2);
      }
      dispatch({ type: "SET_SETTINGS", settings: providerKeys });
      if (shouldRestartBackend && state.backendStatus === "running") await api.backend?.restart();
      setKeysSaved(true);
      setTimeout(() => setKeysSaved(false), 1800);
    } finally {
      setKeysSaving(false);
    }
  };
  if (loading) return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-loading", children: "Loading service integrations…" });
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-topbar", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-topbar-left", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-page-title", children: "Service Integrations" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-page-sub", children: "External systems your agents can connect to once credentials are configured" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", onClick: load, children: "↺ Refresh" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-skills-body", children: [
      err && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-error-banner", children: [
        "⚠ ",
        err,
        " ",
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { onClick: () => setErr(null), children: "✕" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-add-card", style: { maxWidth: 700 }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-add-title", children: "Model & API Keys" }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-form-grid", style: { gridTemplateColumns: "170px 1fr" }, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Anthropic API Key" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", type: "password", placeholder: "sk-ant-…", value: providerKeys.anthropicKey || "", onChange: (e) => setProviderKeys((v2) => ({ ...v2, anthropicKey: e.target.value })) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "OpenAI API Key" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", type: "password", placeholder: "sk-…", value: providerKeys.openaiKey || "", onChange: (e) => setProviderKeys((v2) => ({ ...v2, openaiKey: e.target.value })) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "OpenAI Org ID" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", placeholder: "org-…", value: providerKeys.openaiOrgId || "", onChange: (e) => setProviderKeys((v2) => ({ ...v2, openaiOrgId: e.target.value })) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Google API Key" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", type: "password", placeholder: "AIza…", value: providerKeys.googleKey || "", onChange: (e) => setProviderKeys((v2) => ({ ...v2, googleKey: e.target.value })) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "xAI API Key" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", type: "password", placeholder: "xai-…", value: providerKeys.xaiKey || "", onChange: (e) => setProviderKeys((v2) => ({ ...v2, xaiKey: e.target.value })) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "HuggingFace Token" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", type: "password", placeholder: "hf_…", value: providerKeys.hfToken || "", onChange: (e) => setProviderKeys((v2) => ({ ...v2, hfToken: e.target.value })) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Tavily Key" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", type: "password", placeholder: "tvly-…", value: providerKeys.tavilyKey || "", onChange: (e) => setProviderKeys((v2) => ({ ...v2, tavilyKey: e.target.value })) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Brave Key" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", type: "password", value: providerKeys.braveKey || "", onChange: (e) => setProviderKeys((v2) => ({ ...v2, braveKey: e.target.value })) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "pp-form-label", children: "Serper Key" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "pp-input", type: "password", value: providerKeys.serperKey || "", onChange: (e) => setProviderKeys((v2) => ({ ...v2, serperKey: e.target.value })) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-form-actions", style: { marginTop: 10 }, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--primary", onClick: saveProviderKeys, disabled: keysSaving, children: keysSaving ? "Saving…" : "Save API Keys" }),
          keysSaved && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "pp-form-label", style: { marginBottom: 0 }, children: "Saved" })
        ] })
      ] }),
      integrations.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "pp-empty", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-icon", children: "🧩" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-title", children: "No service integrations found" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pp-empty-sub", children: "Service integrations are exposed by the Kendr backend. Make sure the gateway is running." })
      ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "flex", flexDirection: "column", gap: 12 }, children: ["ready", "needs_config"].map((status) => {
        const group = integrations.filter((p2) => p2.status === status);
        if (!group.length) return null;
        return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em" }, children: status === "ready" ? "✓ Configured" : "⚙ Needs Configuration" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 12 }, children: group.map((p2) => /* @__PURE__ */ jsxRuntimeExports.jsx(
            IntegrationCard,
            {
              integration: p2,
              base,
              onSaved: load
            },
            p2.agent_name
          )) })
        ] }, status);
      }) })
    ] })
  ] });
}
function IntegrationCard({ integration: p2, base, onSaved }) {
  const configured = p2.status === "ready";
  const [expanded, setExpanded] = reactExports.useState(false);
  const [formLoading, setFormLoading] = reactExports.useState(true);
  const [saving, setSaving] = reactExports.useState(false);
  const [saved, setSaved] = reactExports.useState(false);
  const [err, setErr] = reactExports.useState(null);
  const [fields, setFields] = reactExports.useState(null);
  const [values, setValues] = reactExports.useState({});
  const [componentId, setComponentId] = reactExports.useState("");
  const [oauthPath, setOauthPath] = reactExports.useState(null);
  const [hint, setHint] = reactExports.useState(null);
  const openForm = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (fields !== null) {
      setFormLoading(false);
      return;
    }
    setFormLoading(true);
    setErr(null);
    const rawId = integrationIdFromConnector(p2);
    const cid = resolveSetupComponentId(rawId);
    setComponentId(cid);
    let loaded = false;
    if (cid) {
      try {
        const r2 = await fetch(`${base}/api/setup/component/${encodeURIComponent(cid)}`);
        const data = await r2.json().catch(() => ({}));
        if (r2.ok && !data.error && data.component?.fields?.length) {
          const raw = data.raw_values && typeof data.raw_values === "object" ? data.raw_values : {};
          const initVals = {};
          for (const f2 of data.component.fields) {
            const k2 = String(f2.key || "").trim();
            if (k2) initVals[k2] = String(raw[k2] ?? "");
          }
          setFields(data.component.fields);
          setValues(initVals);
          setOauthPath(data.component.oauth_start_path || null);
          setHint(data.component.description || data.component.setup_hint || null);
          loaded = true;
        }
      } catch (_2) {
      }
    }
    if (!loaded) {
      const missing = p2.missing_config || [];
      setFields(missing.map((k2) => ({ key: k2, label: k2, secret: true, required: true })));
      setValues(Object.fromEntries(missing.map((k2) => [k2, ""])));
    }
    setFormLoading(false);
  };
  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const r2 = await fetch(`${base}/api/setup/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ component_id: componentId || integrationIdFromConnector(p2), values })
      });
      const data = await r2.json().catch(() => ({}));
      if (!r2.ok || data.error) throw new Error(data.error || r2.statusText);
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
      await onSaved?.();
      setExpanded(false);
      setFields(null);
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: {
    background: "var(--bg-secondary)",
    border: `1px solid ${configured ? "var(--border)" : expanded ? "#e6a70066" : "#e6a70033"}`,
    borderRadius: 10,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden"
  }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { padding: "14px 16px", display: "flex", flexDirection: "column", gap: 8 }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 10 }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 24, lineHeight: 1 }, children: p2.icon }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { flex: 1, minWidth: 0 }, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontWeight: 600, fontSize: 14 }, children: p2.display_name }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 11, color: "var(--text-muted)" }, children: p2.category })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: {
          fontSize: 11,
          padding: "2px 8px",
          borderRadius: 4,
          flexShrink: 0,
          background: configured ? "#27ae6015" : "#e6a70015",
          color: configured ? "#27ae60" : "#e6a700",
          border: `1px solid ${configured ? "#27ae6044" : "#e6a70044"}`,
          fontWeight: 600
        }, children: configured ? "✓ Ready" : "⚙ Setup needed" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.4 }, children: p2.description }),
      p2.missing_config?.length > 0 && !expanded && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { fontSize: 11, color: "#e6a700", fontFamily: "var(--font-mono)" }, children: [
        "Missing: ",
        p2.missing_config.join(", ")
      ] }),
      p2.metadata?.required_env_vars?.length > 0 && configured && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { fontSize: 11, color: "#27ae60" }, children: [
        "✓ ",
        p2.metadata.required_env_vars.length,
        " credential",
        p2.metadata.required_env_vars.length !== 1 ? "s" : "",
        " configured"
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { display: "flex", justifyContent: "flex-end" }, children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", style: { fontSize: 12 }, onClick: openForm, children: expanded ? "Cancel" : configured ? "Manage Credentials" : "Set Up →" }) })
    ] }),
    expanded && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { borderTop: "2px solid #e6a700", background: "var(--bg)", padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }, children: formLoading ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)" }, children: "Loading configuration…" }) : /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, fontWeight: 700, color: "#e6a700" }, children: "Configure credentials" }),
      hint && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.4 }, children: hint }),
      fields?.length === 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 12, color: "var(--text-muted)" }, children: "No credentials required for this integration." }),
      fields?.map((field) => {
        const k2 = String(field.key || "").trim();
        if (!k2) return null;
        return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 4 }, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { style: { fontSize: 11, color: "var(--text-muted)", fontWeight: 600 }, children: [
            field.label || k2,
            field.required ? " *" : ""
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              className: "pp-input",
              type: field.secret ? "password" : "text",
              placeholder: field.placeholder || field.default || "",
              value: values[k2] || "",
              onChange: (e) => setValues((v2) => ({ ...v2, [k2]: e.target.value }))
            }
          ),
          field.hint && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { fontSize: 11, color: "var(--text-muted)" }, children: field.hint })
        ] }, k2);
      }),
      oauthPath && /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          className: "pp-btn pp-btn--ghost",
          style: { alignSelf: "flex-start", fontSize: 12 },
          onClick: () => window.open(`${base}${oauthPath}`, "_blank", "noopener"),
          children: "Start OAuth →"
        }
      ),
      err && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { fontSize: 12, color: "#e74c3c" }, children: [
        "⚠ ",
        err
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 2 }, children: [
        saved && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { fontSize: 12, color: "#27ae60", alignSelf: "center" }, children: "Saved" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--ghost", style: { fontSize: 12 }, onClick: () => setExpanded(false), children: "Cancel" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "pp-btn pp-btn--primary", style: { fontSize: 12 }, onClick: save, disabled: saving, children: saving ? "Saving…" : "Save" })
      ] })
    ] }) })
  ] });
}
function MachineHub() {
  const { state } = useApp();
  const apiBase = state.backendUrl || "http://127.0.0.1:2151";
  const workingDirectory = (state.projectRoot || state.settings?.projectRoot || "").trim();
  const [data, setData] = reactExports.useState(null);
  const [loading, setLoading] = reactExports.useState(false);
  const [error, setError] = reactExports.useState("");
  const fetchDetails = reactExports.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const q2 = new URLSearchParams();
      if (workingDirectory) q2.set("working_directory", workingDirectory);
      q2.set("max_files", "20000");
      const resp = await fetch(`${apiBase}/api/machine/details?${q2.toString()}`);
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(body?.error || `machine_${resp.status}`);
      setData(body || null);
    } catch (err) {
      setError(String(err?.message || err || "Failed to load machine details"));
    } finally {
      setLoading(false);
    }
  }, [apiBase, workingDirectory]);
  reactExports.useEffect(() => {
    fetchDetails();
  }, [fetchDetails]);
  const apps = Array.isArray(data?.apps) ? data.apps : [];
  const status = data?.status || {};
  const system = data?.system_info || status?.system_info || {};
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kendr-page machine-page", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "hero-card machine-hero", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "hero-copy", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "eyebrow", children: "Machine" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("h1", { children: "See machine facts and available apps." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Keep this view focused on system snapshot and synced software inventory." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "hero-actions", children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--primary", onClick: fetchDetails, disabled: loading, children: loading ? "Refreshing…" : "Refresh" }) }),
        error && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "machine-error", children: error }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "machine-note", children: [
          "Workspace root: ",
          system.workspace_root || data?.working_directory || "unknown"
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "hero-metrics", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(MetricCard$1, { label: "Apps", value: String(Number(status?.installed_software_count || 0)), detail: "Installed tools in snapshot" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(MetricCard$1, { label: "Host", value: system.hostname || "unknown", detail: system.architecture || "unknown" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(MetricCard$1, { label: "Memory", value: system.total_memory_gb ? `${system.total_memory_gb} GB` : "unknown", detail: system.python_version ? `Python ${system.python_version}` : "Python unknown" })
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "grid-two machine-grid", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card machine-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(SectionHeader$1, { title: "System Snapshot", subtitle: "Machine-wide environment facts" }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "machine-kv-grid", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(KeyValue, { label: "Host", value: system.hostname || "unknown" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(KeyValue, { label: "OS", value: [system.os, system.os_release].filter(Boolean).join(" ") || system.platform || "unknown" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(KeyValue, { label: "Arch", value: system.architecture || "unknown" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(KeyValue, { label: "Python", value: system.python_version || "unknown" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(KeyValue, { label: "CPU Cores", value: String(system.cpu_count || 0) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(KeyValue, { label: "Memory", value: system.total_memory_gb ? `${system.total_memory_gb} GB` : "unknown" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(KeyValue, { label: "Disk Root", value: system.disk_root || "unknown" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(KeyValue, { label: "Disk Free", value: system.disk_free_gb ? `${system.disk_free_gb} GB` : "unknown" })
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card machine-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(SectionHeader$1, { title: "Synced Apps", subtitle: "Software inventory snapshot" }),
        apps.length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "empty-state", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "empty-state__title", children: "No apps synced yet" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "empty-state__body", children: "Run machine sync first." })
        ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "machine-app-list machine-app-list--scroll", children: apps.map((app) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "machine-app-row", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "machine-app-row__name", children: app.name }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "machine-app-row__meta", children: app.version || "version unknown" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "machine-app-row__path", title: app.path || "", children: app.path || "path unknown" })
        ] }, `${app.name}-${app.path || ""}`)) })
      ] })
    ] })
  ] });
}
function SectionHeader$1({ title, subtitle }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: title }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: subtitle })
  ] }) });
}
function MetricCard$1({ label, value, detail }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "metric-card", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "metric-card__label", children: label }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "metric-card__value", children: value }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "metric-card__detail", children: detail })
  ] });
}
function KeyValue({ label, value }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "machine-kv", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "machine-kv__label", children: label }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "machine-kv__value", title: value, children: value })
  ] });
}
function MemoryHub() {
  const { state, dispatch } = useApp();
  const localModels = Array.isArray(state.ollamaModels) ? state.ollamaModels.length : 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kendr-page", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "surface-card", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: "Memory" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Turn documents, local files, and saved workspace context into reusable knowledge for assistants and workflows." })
      ] }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "memory-grid", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          MemoryCard,
          {
            title: "Knowledge Bases",
            body: "Build reusable retrieval layers from folders, URLs, databases, and cloud drives.",
            badge: "RAG-ready"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          MemoryCard,
          {
            title: "Session Memory",
            body: "Keep short-term context across a conversation or run without overloading the prompt.",
            badge: "Ephemeral"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          MemoryCard,
          {
            title: "Long-Term Memory",
            body: "Store durable notes, run outcomes, and workspace knowledge across tasks.",
            badge: "Persistent"
          }
        )
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "grid-two", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: "Recommended Next Step" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "The memory console is not fully surfaced in the desktop app yet, but the platform primitives already exist." })
        ] }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "action-row", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "action-row__title", children: "Use Studio for memory-backed assistants" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "action-row__detail", children: "Start in Studio, then attach knowledge and tools as your workflows mature." })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--ghost", onClick: () => dispatch({ type: "SET_VIEW", view: "studio" }), children: "Open Studio" })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "action-row", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "action-row__title", children: "Inspect retrieval activity through runs" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "action-row__detail", children: "Use the run inspector to validate what the assistant used and what it missed." })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--ghost", onClick: () => dispatch({ type: "SET_VIEW", view: "runs" }), children: "Open Runs" })
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: "Environment Snapshot" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Key setup signals that influence memory and retrieval behavior." })
        ] }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-grid", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-pill status-pill--neutral", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__label", children: "Backend status" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__value", children: state.backendStatus })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-pill status-pill--neutral", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__label", children: "Project root" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__value", children: state.projectRoot ? state.projectRoot.split(/[\\/]/).pop() : "Not connected" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-pill status-pill--neutral", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__label", children: "Selected model" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__value", children: state.selectedModel || "Auto" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "status-pill status-pill--neutral", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__label", children: "Local models" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-pill__value", children: localModels })
          ] })
        ] })
      ] })
    ] })
  ] });
}
function MemoryCard({ title, body, badge }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "memory-card", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "memory-card__badge", children: badge }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("h3", { children: title }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: body })
  ] });
}
const TABS$1 = [
  { id: "general", label: "General" },
  { id: "keys", label: "API Keys" },
  { id: "rag", label: "RAG & Data" },
  { id: "models", label: "Models" },
  { id: "editor", label: "Editor" },
  { id: "chat", label: "Chat" }
];
function formatDateTime(value) {
  if (!value) return "Not checked yet";
  const ts = new Date(value);
  if (Number.isNaN(ts.getTime())) return "Not checked yet";
  return ts.toLocaleString();
}
function describeFeed(updateStatus, settings) {
  const savedFeed = String(settings.updateBaseUrl || "").trim();
  if (savedFeed) return savedFeed;
  if (updateStatus.feedSource === "packaged") return "Packaged release feed";
  if (updateStatus.feedSource === "env" && updateStatus.feedUrl) return updateStatus.feedUrl;
  return "Not configured";
}
function describeUpdateStatus(updateStatus) {
  if (!updateStatus) return "Update status unavailable.";
  if (updateStatus.status === "downloading" && updateStatus.progress?.percent != null) {
    const percent = Math.max(0, Math.min(100, Number(updateStatus.progress.percent || 0)));
    return `Downloading update (${percent.toFixed(percent >= 10 ? 0 : 1)}%).`;
  }
  return updateStatus.message || "Update status unavailable.";
}
function Settings() {
  const { state, dispatch } = useApp();
  const [tab, setTab] = reactExports.useState("general");
  const [settings, setSettings] = reactExports.useState({});
  const [saved, setSaved] = reactExports.useState(false);
  const [machineStatus, setMachineStatus] = reactExports.useState(null);
  const [machineStatusLoading, setMachineStatusLoading] = reactExports.useState(false);
  const api = window.kendrAPI;
  const apiBase = state.backendUrl || "http://127.0.0.1:2151";
  const providerSettingKeys = ["anthropicKey", "openaiKey", "openaiOrgId", "googleKey", "xaiKey"];
  reactExports.useEffect(() => {
    api?.settings.getAll().then((s2) => setSettings(s2 || {}));
  }, []);
  const syncWorkingDirectory = (state.projectRoot || state.settings?.projectRoot || settings.projectRoot || "").trim();
  const fetchMachineStatus = async () => {
    setMachineStatusLoading(true);
    try {
      const q2 = syncWorkingDirectory ? `?working_directory=${encodeURIComponent(syncWorkingDirectory)}` : "";
      const resp = await fetch(`${apiBase}/api/machine/status${q2}`);
      if (!resp.ok) return;
      const data = await resp.json().catch(() => ({}));
      const status = data?.status && typeof data.status === "object" ? data.status : null;
      if (status) setMachineStatus(status);
    } catch (_2) {
    } finally {
      setMachineStatusLoading(false);
    }
  };
  const refreshMachineSync = async () => {
    setMachineStatusLoading(true);
    try {
      const resp = await fetch(`${apiBase}/api/machine/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: "machine",
          working_directory: syncWorkingDirectory || void 0
        })
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) return;
      const status = data?.status && typeof data.status === "object" ? data.status : null;
      if (status) setMachineStatus(status);
    } catch (_2) {
    } finally {
      setMachineStatusLoading(false);
    }
  };
  reactExports.useEffect(() => {
    if (tab !== "general") return;
    fetchMachineStatus();
  }, [tab, apiBase, syncWorkingDirectory]);
  const update = (key, value) => setSettings((s2) => ({ ...s2, [key]: value }));
  const save = async () => {
    const shouldRestartBackend = providerSettingKeys.some((key) => (state.settings?.[key] || "") !== (settings?.[key] || ""));
    for (const [k2, v2] of Object.entries(settings)) {
      await api?.settings.set(k2, v2);
    }
    dispatch({ type: "SET_SETTINGS", settings });
    if (settings.backendUrl) dispatch({ type: "SET_BACKEND_URL", url: settings.backendUrl });
    if (settings.projectRoot) dispatch({ type: "SET_PROJECT_ROOT", root: settings.projectRoot });
    if (shouldRestartBackend && state.backendStatus === "running") await api?.backend.restart();
    setSaved(true);
    setTimeout(() => setSaved(false), 2e3);
  };
  const openFolder = async (key) => {
    const dir = await api?.dialog.openDirectory();
    if (dir) update(key, dir);
  };
  const s = settings;
  const updateStatus = state.updateStatus || {};
  const updateFeed = describeFeed(updateStatus, s);
  const updateSummary = describeUpdateStatus(updateStatus);
  const updateVersion = updateStatus.downloadedVersion || updateStatus.availableVersion || updateStatus.currentVersion || "unknown";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-tabs", children: TABS$1.map((t2) => /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        className: `st-tab ${tab === t2.id ? "active" : ""}`,
        onClick: () => setTab(t2.id),
        children: t2.label
      },
      t2.id
    )) }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-body", children: [
      tab === "general" && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Backend", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Kendr Root", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-input-row", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.kendrRoot || "", onChange: (e) => update("kendrRoot", e.target.value), placeholder: "auto-detected" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-browse", onClick: () => openFolder("kendrRoot"), children: "…" })
          ] }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "UI Server URL", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.backendUrl || "http://127.0.0.1:2151", onChange: (e) => update("backendUrl", e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Gateway URL", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.gatewayUrl || "http://127.0.0.1:8790", onChange: (e) => update("gatewayUrl", e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Python Path", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.pythonPath || "", onChange: (e) => update("pythonPath", e.target.value), placeholder: "python" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Project Root", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-input-row", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.projectRoot || "", onChange: (e) => update("projectRoot", e.target.value) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-browse", onClick: () => openFolder("projectRoot"), children: "…" })
          ] }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Auto-start backend", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", className: "st-check", checked: !!s.autoStartBackend, onChange: (e) => update("autoStartBackend", e.target.checked) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-actions", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-btn-accent", onClick: () => api?.backend.restart(), children: "Restart Backend" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-btn", onClick: () => api?.backend.stop(), children: "Stop" })
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Git", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Display Name", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.gitName || "", onChange: (e) => update("gitName", e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Email", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.gitEmail || "", onChange: (e) => update("gitEmail", e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "GitHub PAT", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.githubPat || "", onChange: (e) => update("githubPat", e.target.value), placeholder: "ghp_…" }) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Application Updates", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Enable Remote Updates", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", className: "st-check", checked: s.updatesEnabled !== false, onChange: (e) => update("updatesEnabled", e.target.checked) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Update Feed URL", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              className: "st-input",
              value: s.updateBaseUrl || "",
              onChange: (e) => update("updateBaseUrl", e.target.value),
              placeholder: "Use the packaged release feed when left blank"
            }
          ) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Update Channel", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              className: "st-input st-input--sm",
              value: s.updateChannel || "latest",
              onChange: (e) => update("updateChannel", e.target.value),
              placeholder: "latest"
            }
          ) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Check Every (minutes)", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              className: "st-input st-input--sm",
              type: "number",
              min: "15",
              max: "1440",
              value: Number(s.updateCheckIntervalMinutes || 240),
              onChange: (e) => update("updateCheckIntervalMinutes", Math.max(15, Math.min(1440, Number(e.target.value || 240))))
            }
          ) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Auto-download Releases", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", className: "st-check", checked: s.autoDownloadUpdates !== false, onChange: (e) => update("autoDownloadUpdates", e.target.checked) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Install on Quit", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", className: "st-check", checked: s.autoInstallOnQuit !== false, onChange: (e) => update("autoInstallOnQuit", e.target.checked) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Allow Pre-release Versions", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", className: "st-check", checked: !!s.allowPrereleaseUpdates, onChange: (e) => update("allowPrereleaseUpdates", e.target.checked) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-info-banner", children: updateSummary }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-info-banner", style: { marginTop: 8 }, children: `Current version: ${updateStatus.currentVersion || "unknown"} · Target version: ${updateVersion} · Feed: ${updateFeed} · Last check: ${formatDateTime(updateStatus.checkedAt)}` }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-actions", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-btn", onClick: () => api?.updates?.check(), disabled: updateStatus.status === "checking", children: updateStatus.status === "checking" ? "Checking…" : "Check for Updates" }),
            updateStatus.status === "available" && updateStatus.autoDownload === false && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-btn-accent", onClick: () => api?.updates?.download(), children: "Download Update" }),
            updateStatus.status === "downloaded" && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-btn-accent", onClick: () => api?.updates?.install(), children: "Restart to Update" })
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Machine Sync", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Auto Sync Machine Index", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              type: "checkbox",
              className: "st-check",
              checked: !!s.machineAutoSyncEnabled,
              onChange: (e) => update("machineAutoSyncEnabled", e.target.checked)
            }
          ) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Auto Sync Every (days)", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              className: "st-input st-input--sm",
              type: "number",
              min: "1",
              max: "30",
              value: Number(s.machineAutoSyncIntervalDays || 7),
              onChange: (e) => update("machineAutoSyncIntervalDays", Math.max(1, Math.min(30, Number(e.target.value || 7))))
            }
          ) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-actions", children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-btn", onClick: refreshMachineSync, disabled: machineStatusLoading, children: machineStatusLoading ? "Refreshing…" : "Refresh Machine Index" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-info-banner", children: machineStatus?.software_inventory_last_synced ? `Last machine sync: ${new Date(machineStatus.software_inventory_last_synced).toLocaleString()}` : "No machine sync snapshot yet. Run machine sync once." }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-machine-apps", children: (Array.isArray(machineStatus?.discovered_apps) ? machineStatus.discovered_apps : []).length === 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-machine-empty", children: "No discovered apps yet." }) : (machineStatus.discovered_apps || []).map((app) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-machine-app", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-machine-app-name", children: app.name }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-machine-app-meta", children: [
              app.version || "version unknown",
              app.path ? ` · ${app.path}` : ""
            ] })
          ] }, `${app.name}-${app.path || ""}`)) })
        ] })
      ] }),
      tab === "keys" && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-info-banner", children: "API keys are stored locally via electron-store and never sent to any server other than the respective provider." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(Section, { title: "Anthropic", children: /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "API Key", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.anthropicKey || "", onChange: (e) => update("anthropicKey", e.target.value), placeholder: "sk-ant-…" }) }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "OpenAI", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "API Key", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.openaiKey || "", onChange: (e) => update("openaiKey", e.target.value), placeholder: "sk-…" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Org ID", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.openaiOrgId || "", onChange: (e) => update("openaiOrgId", e.target.value), placeholder: "org-…" }) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(Section, { title: "Google AI", children: /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "API Key", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.googleKey || "", onChange: (e) => update("googleKey", e.target.value), placeholder: "AIza…" }) }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(Section, { title: "xAI / Grok", children: /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "API Key", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.xaiKey || "", onChange: (e) => update("xaiKey", e.target.value), placeholder: "xai-…" }) }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(Section, { title: "HuggingFace", children: /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Token", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.hfToken || "", onChange: (e) => update("hfToken", e.target.value), placeholder: "hf_…" }) }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Other", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Tavily (Web Search)", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.tavilyKey || "", onChange: (e) => update("tavilyKey", e.target.value), placeholder: "tvly-…" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Brave Search", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.braveKey || "", onChange: (e) => update("braveKey", e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Serper API", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.serperKey || "", onChange: (e) => update("serperKey", e.target.value) }) })
        ] })
      ] }),
      tab === "rag" && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-info-banner", children: "Configure RAG infrastructure defaults here. Deep Research can optionally consume an indexed KB at run time, but KB creation and indexing live in Super-RAG." }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Vector Store", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Backend", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "st-select", value: s.vectorStore || "chroma", onChange: (e) => update("vectorStore", e.target.value), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "chroma", children: "Chroma (local)" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "pinecone", children: "Pinecone" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "weaviate", children: "Weaviate" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "qdrant", children: "Qdrant" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "pgvector", children: "pgvector (Postgres)" })
          ] }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Host / URL", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.vectorStoreUrl || "", onChange: (e) => update("vectorStoreUrl", e.target.value), placeholder: "http://localhost:8000" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "API Key", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.vectorStoreKey || "", onChange: (e) => update("vectorStoreKey", e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Collection / Index", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.vectorCollection || "kendr_docs", onChange: (e) => update("vectorCollection", e.target.value) }) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Embedding Model", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Provider", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "st-select", value: s.embedProvider || "openai", onChange: (e) => update("embedProvider", e.target.value), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "openai", children: "OpenAI (text-embedding-3-small)" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "anthropic", children: "Anthropic (voyage-3)" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "google", children: "Google (text-embedding-004)" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "ollama", children: "Ollama (nomic-embed-text)" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "huggingface", children: "HuggingFace (local)" })
          ] }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Model Override", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.embedModel || "", onChange: (e) => update("embedModel", e.target.value), placeholder: "leave blank for default" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Dimensions", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", value: s.embedDims || 1536, onChange: (e) => update("embedDims", +e.target.value) }) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Document Sources", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Local Scan Paths", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-input-row", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.ragLocalPaths || "", onChange: (e) => update("ragLocalPaths", e.target.value), placeholder: "comma-separated folder paths" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-browse", onClick: async () => {
              const dir = await api?.dialog.openDirectory();
              if (dir) update("ragLocalPaths", s.ragLocalPaths ? `${s.ragLocalPaths},${dir}` : dir);
            }, children: "…" })
          ] }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Chunk Size", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", value: s.ragChunkSize || 512, onChange: (e) => update("ragChunkSize", +e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Chunk Overlap", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", value: s.ragChunkOverlap || 64, onChange: (e) => update("ragChunkOverlap", +e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Auto-index on start", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", className: "st-check", checked: !!s.ragAutoIndex, onChange: (e) => update("ragAutoIndex", e.target.checked) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-actions", children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-btn-accent", onClick: () => {
            try {
              window.open(`${apiBase}/rag`, "_blank", "noopener,noreferrer");
            } catch (_2) {
            }
          }, children: "Open Super-RAG" }) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Web Connectors", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Confluence URL", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.confluenceUrl || "", onChange: (e) => update("confluenceUrl", e.target.value), placeholder: "https://company.atlassian.net" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Confluence Token", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.confluenceToken || "", onChange: (e) => update("confluenceToken", e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Notion Token", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", type: "password", value: s.notionToken || "", onChange: (e) => update("notionToken", e.target.value), placeholder: "ntn_…" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "SharePoint Tenant", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.sharepointTenant || "", onChange: (e) => update("sharepointTenant", e.target.value), placeholder: "tenant.sharepoint.com" }) })
        ] })
      ] }),
      tab === "models" && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Default Model", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Provider", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "st-select", value: s.defaultProvider || "auto", onChange: (e) => update("defaultProvider", e.target.value), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "auto", children: "Auto (backend decides)" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "anthropic", children: "Anthropic" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "openai", children: "OpenAI" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "google", children: "Google" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "ollama", children: "Ollama (local)" })
          ] }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Model ID", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.defaultModel || "", onChange: (e) => update("defaultModel", e.target.value), placeholder: "e.g. claude-sonnet-4-6 or llama3.2" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Temperature", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", min: "0", max: "2", step: "0.1", value: s.temperature ?? 0.7, onChange: (e) => update("temperature", +e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Max Tokens", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", value: s.maxTokens || 4096, onChange: (e) => update("maxTokens", +e.target.value) }) })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Ollama", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Model Download Dir", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-input-row", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.modelDownloadDir || "", onChange: (e) => update("modelDownloadDir", e.target.value) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-browse", onClick: () => openFolder("modelDownloadDir"), children: "…" })
          ] }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "GPU Layers", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", min: "0", value: s.gpuLayers || 0, onChange: (e) => update("gpuLayers", +e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Context Size", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", value: s.contextSize || 4096, onChange: (e) => update("contextSize", +e.target.value) }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Threads", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", min: "1", max: "32", value: s.threads || 4, onChange: (e) => update("threads", +e.target.value) }) })
        ] })
      ] }),
      tab === "editor" && /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "Editor Preferences", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Font Size", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", min: "10", max: "24", value: s.fontSize || 14, onChange: (e) => update("fontSize", +e.target.value) }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Tab Size", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input st-input--sm", type: "number", min: "2", max: "8", value: s.tabSize || 2, onChange: (e) => update("tabSize", +e.target.value) }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Font Family", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { className: "st-input", value: s.fontFamily || "", onChange: (e) => update("fontFamily", e.target.value), placeholder: "'Cascadia Code', monospace" }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Word Wrap", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("select", { className: "st-select", value: s.wordWrap || "off", onChange: (e) => update("wordWrap", e.target.value), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "off", children: "Off" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "on", children: "On" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("option", { value: "wordWrapColumn", children: "Column" })
        ] }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Minimap", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", className: "st-check", checked: s.minimap !== false, onChange: (e) => update("minimap", e.target.checked) }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Format on Save", children: /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", className: "st-check", checked: !!s.formatOnSave, onChange: (e) => update("formatOnSave", e.target.checked) }) })
      ] }),
      tab === "chat" && /* @__PURE__ */ jsxRuntimeExports.jsx(jsxRuntimeExports.Fragment, { children: /* @__PURE__ */ jsxRuntimeExports.jsxs(Section, { title: "History", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(Row, { label: "Retention Period", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 8 }, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              className: "st-input st-input--sm",
              type: "number",
              min: "0",
              max: "365",
              value: s.chatHistoryRetentionDays ?? 14,
              onChange: (e) => update("chatHistoryRetentionDays", +e.target.value)
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "st-hint", children: "days  (0 = keep forever)" })
        ] }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-info-banner", style: { marginTop: 8 }, children: [
          "Chat history is stored locally on your device. Conversations older than the retention period are automatically deleted when the app loads. Default is ",
          /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { children: "14 days" }),
          "."
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-actions", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            className: "st-btn",
            onClick: () => {
              if (window.confirm("Delete all chat history? This cannot be undone.")) {
                localStorage.removeItem("kendr_sessions_v1");
                localStorage.removeItem("kendr_chat_history_v1");
              }
            },
            children: "Clear All History"
          }
        ) })
      ] }) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-footer", children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "st-btn-accent", onClick: save, children: saved ? "✓ Saved" : "Save Settings" }) })
  ] });
}
function Section({ title, children }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-section", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-section-title", children: title }),
    children
  ] });
}
function Row({ label, children }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "st-row", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("label", { className: "st-label", children: label }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "st-control", children })
  ] });
}
function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const digits = size >= 10 || unitIndex === 0 ? 0 : 1;
  return `${size.toFixed(digits)} ${units[unitIndex]}`;
}
function ModelManager() {
  const { state } = useApp();
  const [ollamaModels, setOllamaModels] = reactExports.useState([]);
  const [guide, setGuide] = reactExports.useState(null);
  const [loadingModels, setLoadingModels] = reactExports.useState(true);
  const [loadingGuide, setLoadingGuide] = reactExports.useState(true);
  const [pullTag, setPullTag] = reactExports.useState("");
  const [pullState, setPullState] = reactExports.useState(null);
  const [pulling, setPulling] = reactExports.useState(false);
  const [deletingModel, setDeletingModel] = reactExports.useState("");
  const [pullStatus, setPullStatus] = reactExports.useState(null);
  const backendUrl = state.backendUrl || "http://127.0.0.1:2151";
  const fetchModels = async () => {
    setLoadingModels(true);
    try {
      const r2 = await fetch(`${backendUrl}/api/models/ollama`);
      if (r2.ok) {
        const data = await r2.json();
        setOllamaModels(Array.isArray(data.models) ? data.models : []);
      }
    } catch (_2) {
    } finally {
      setLoadingModels(false);
    }
  };
  const fetchGuide = async (force = false) => {
    setLoadingGuide(true);
    try {
      const suffix = force ? "?refresh=1" : "";
      const r2 = await fetch(`${backendUrl}/api/models/guide${suffix}`);
      if (r2.ok) {
        const data = await r2.json();
        setGuide(data || null);
      }
    } catch (_2) {
    } finally {
      setLoadingGuide(false);
    }
  };
  const fetchPullStatus = async () => {
    try {
      const r2 = await fetch(`${backendUrl}/api/models/ollama/pull/status`);
      if (!r2.ok) return;
      const data = await r2.json();
      setPullState(data);
      const live = Boolean(data.active) && ["starting", "running", "cancelling"].includes(data.status);
      setPulling(live);
      if (!live && data.status === "completed") {
        fetchModels();
        fetchGuide(true);
      }
    } catch (_2) {
    }
  };
  reactExports.useEffect(() => {
    fetchModels();
    fetchGuide(false);
    fetchPullStatus();
  }, [backendUrl]);
  reactExports.useEffect(() => {
    if (!pullState?.active || !["starting", "running", "cancelling"].includes(pullState.status)) return;
    const timer = setInterval(() => {
      fetchPullStatus();
    }, 900);
    return () => clearInterval(timer);
  }, [backendUrl, pullState?.active, pullState?.status]);
  reactExports.useEffect(() => {
    const timer = setInterval(() => {
      fetchGuide(true);
    }, 10 * 60 * 1e3);
    return () => clearInterval(timer);
  }, [backendUrl]);
  const pullModelWithValue = async (modelName) => {
    const model = String(modelName || "").trim();
    if (!model || pulling) return;
    setPullTag(model);
    setPullStatus(null);
    try {
      const r2 = await fetch(`${backendUrl}/api/models/ollama/pull`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model })
      });
      const data = await r2.json().catch(() => ({}));
      if ((r2.ok || r2.status === 202) && data.ok) {
        setPulling(true);
        setPullState(data.pull || null);
        setPullStatus(null);
        fetchGuide(true);
      } else {
        setPullStatus({ ok: false, msg: data.error || `Pull failed (${r2.status})` });
      }
    } catch (e) {
      setPullStatus({ ok: false, msg: `Network error: ${e.message}` });
    }
  };
  const pullModel = async () => {
    await pullModelWithValue(pullTag);
  };
  const cancelPull = async () => {
    try {
      const r2 = await fetch(`${backendUrl}/api/models/ollama/pull/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      const data = await r2.json().catch(() => ({}));
      if (r2.ok && data.ok) {
        setPullState(data.pull || null);
        setPulling(Boolean(data.pull?.active));
      } else {
        setPullStatus({ ok: false, msg: data.error || `Cancel failed (${r2.status})` });
      }
    } catch (e) {
      setPullStatus({ ok: false, msg: `Network error: ${e.message}` });
    }
  };
  const deleteModel = async (modelName) => {
    const model = String(modelName || "").trim();
    if (!model || deletingModel) return;
    setDeletingModel(model);
    setPullStatus(null);
    try {
      const r2 = await fetch(`${backendUrl}/api/models/ollama/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model })
      });
      const data = await r2.json().catch(() => ({}));
      if (r2.ok && data.ok) {
        setPullStatus({ ok: true, msg: `Deleted ${model}` });
        fetchModels();
        fetchGuide(true);
      } else {
        setPullStatus({ ok: false, msg: data.detail || data.error || `Delete failed (${r2.status})` });
      }
    } catch (e) {
      setPullStatus({ ok: false, msg: `Network error: ${e.message}` });
    } finally {
      setDeletingModel("");
    }
  };
  const activePull = pullState && (pullState.active || ["completed", "failed", "cancelled"].includes(pullState.status)) ? pullState : null;
  const progressPercent = Number(activePull?.percent || 0);
  const hasDeterminateProgress = Number(activePull?.total || 0) > 0;
  const progressWidth = hasDeterminateProgress ? `${Math.max(0, Math.min(100, progressPercent))}%` : "35%";
  const recommendations = Array.isArray(guide?.recommendations) ? guide.recommendations : [];
  const cloudUsage = Array.isArray(guide?.cloud_usage) ? guide.cloud_usage : [];
  const rankings = Array.isArray(guide?.openrouter_rankings) ? guide.openrouter_rankings.slice(0, 5) : [];
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-manager", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sidebar-label", children: "RECOMMENDED NEXT" }),
    loadingGuide && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sidebar-empty", children: "Building model guide…" }),
    !loadingGuide && recommendations.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-reco-grid", children: recommendations.slice(0, 6).map((item) => {
      const isPulled = item.status === "pulled";
      const isCloud = item.access === "cloud";
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: `model-reco-card ${item.fits_system ? "" : "model-reco-card--dim"}`, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-reco-top", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-reco-name", children: item.label }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-reco-meta", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `model-mini-chip ${isCloud ? "cloud" : "local"}`, children: isCloud ? "cloud" : "local" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "model-mini-chip", children: item.speed }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "model-mini-chip", children: item.cost })
            ] })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-reco-size", children: isCloud ? "No local GB" : `${Number(item.size_gb || 0).toFixed(1)} GB` })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-reco-fit", children: item.fit_label }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-reco-copy", children: Array.isArray(item.best_for) ? item.best_for.join(" • ") : "" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-reco-copy", children: Array.isArray(item.agent_fit) ? `Agents: ${item.agent_fit.join(" • ")}` : "" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-reco-note", children: item.notes }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-reco-actions", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "btn-accent", disabled: pulling || isPulled, onClick: () => pullModelWithValue(item.id), children: isPulled ? "Pulled" : isCloud ? "Add Alias" : "Pull" }),
          isPulled && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "btn-danger", disabled: deletingModel === item.id, onClick: () => deleteModel(item.id), children: deletingModel === item.id ? "Deleting…" : "Delete" })
        ] })
      ] }, item.id);
    }) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sidebar-label", children: "OLLAMA MODELS" }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-pull-row", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "input",
        {
          className: "model-input",
          placeholder: "e.g. llama3.2, mistral, deepseek-r1, kimi-k2.5:cloud",
          value: pullTag,
          onChange: (e) => {
            setPullTag(e.target.value);
            setPullStatus(null);
          },
          onKeyDown: (e) => e.key === "Enter" && pullModel(),
          disabled: pulling
        }
      ),
      !pulling && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "btn-accent", disabled: !pullTag.trim(), onClick: pullModel, children: "Pull" }),
      pulling && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "btn-danger", onClick: cancelPull, children: "Cancel" })
    ] }),
    activePull && activePull.status !== "idle" && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-pull-progress", children: activePull.message || `Downloading ${activePull.model} — this may take a few minutes…` }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-download-card", "aria-live": "polite", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-download-row", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "model-name", children: activePull.model }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "model-download-status", children: [
            activePull.status === "completed" && "Completed",
            activePull.status === "failed" && "Failed",
            activePull.status === "cancelled" && "Cancelled",
            activePull.status === "cancelling" && "Cancelling…",
            ["starting", "running"].includes(activePull.status) && `${progressPercent.toFixed(1)}%`
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-download-meta", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
            formatBytes(activePull.completed),
            " downloaded"
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: hasDeterminateProgress ? `${formatBytes(activePull.total)} total` : "Calculating size…" })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: `model-download-bar ${hasDeterminateProgress ? "" : "indeterminate"}`, role: "progressbar", "aria-label": `Downloading ${activePull.model}`, "aria-valuemin": 0, "aria-valuemax": hasDeterminateProgress ? Number(activePull.total || 0) : 100, "aria-valuenow": hasDeterminateProgress ? Number(activePull.completed || 0) : void 0, children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-download-bar-fill", style: { width: progressWidth } }) }),
        activePull.digest && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-download-detail", children: [
          "Layer: ",
          activePull.digest
        ] }),
        activePull.error && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-download-error", children: activePull.error })
      ] })
    ] }),
    pullStatus && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: `model-pull-result ${pullStatus.ok ? "model-pull-result--ok" : "model-pull-result--err"}`, children: pullStatus.msg }),
    loadingModels && !pulling && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sidebar-empty", children: "Checking Ollama models…" }),
    !loadingModels && ollamaModels.length === 0 && !pulling && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sidebar-empty", children: "No Ollama models found. Pull one above or start Ollama." }),
    !loadingModels && ollamaModels.map((m2) => {
      const name = m2.name || m2;
      const isCloud = String(name).includes(":cloud");
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-item", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-item-main", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "model-name", children: name }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `model-mini-chip ${isCloud ? "cloud" : "local"}`, children: isCloud ? "cloud alias" : "local" })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-item-actions", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "model-size", children: m2.size ? `${(m2.size / 1e9).toFixed(1)} GB` : "" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "btn-danger", disabled: deletingModel === name, onClick: () => deleteModel(name), children: deletingModel === name ? "Deleting…" : "Delete" })
        ] })
      ] }, name);
    }),
    cloudUsage.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sidebar-label", style: { marginTop: 16 }, children: "CLOUD MODELS" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-cloud-guide", children: cloudUsage.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-cloud-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-cloud-title", children: item.title }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-cloud-body", children: item.body })
      ] }, item.title)) })
    ] }),
    rankings.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sidebar-label", style: { marginTop: 16 }, children: "OPENROUTER TOP" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-ranking-list", children: rankings.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "model-ranking-row", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "model-ranking-rank", children: [
          "#",
          item.rank
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "model-ranking-name", children: item.name }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "model-ranking-meta", children: [
          item.tokens,
          " • ",
          item.share
        ] })
      ] }, `${item.rank}:${item.name}`)) })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sidebar-label", style: { marginTop: 16 }, children: "CONFIGURED PROVIDERS" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "model-providers", children: ["openai", "anthropic", "google", "ollama"].map((p2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "provider-row", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "provider-name", children: p2 }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "provider-badge", children: "via kendr setup" })
    ] }, p2)) })
  ] });
}
const capabilityLabel = (value) => value ? "Yes" : "No";
function priceLabel(value) {
  if (value == null) return "—";
  if (value === 0) return "Free";
  return `$${Number(value).toFixed(2)}/M`;
}
function ModelDocs() {
  const { state, refreshModelInventory } = useApp();
  const apiBase = state.backendUrl || "http://127.0.0.1:2151";
  const inventory = state.modelInventory;
  const loadingInventory = !!state.modelInventoryLoading && !inventory;
  const inventoryError = !!state.modelInventoryError;
  const [guide, setGuide] = reactExports.useState(null);
  const [loadingGuide, setLoadingGuide] = reactExports.useState(false);
  const [guideError, setGuideError] = reactExports.useState("");
  const loadGuide = async (force = false) => {
    setLoadingGuide(true);
    setGuideError("");
    try {
      const suffix = force ? "?refresh=1" : "";
      const r2 = await fetch(`${apiBase}/api/models/guide${suffix}`);
      if (!r2.ok) throw new Error(`HTTP ${r2.status}`);
      const data = await r2.json();
      setGuide(data || null);
    } catch (err) {
      setGuideError(err?.message || "Failed to load model guide");
    } finally {
      setLoadingGuide(false);
    }
  };
  reactExports.useEffect(() => {
    refreshModelInventory(false);
    loadGuide(false);
  }, [apiBase, refreshModelInventory]);
  reactExports.useEffect(() => {
    const timer = setInterval(() => {
      loadGuide(true);
    }, 10 * 60 * 1e3);
    return () => clearInterval(timer);
  }, [apiBase]);
  const rows = reactExports.useMemo(() => {
    const comparisonRows = Array.isArray(inventory?.comparison_rows) ? inventory.comparison_rows : [];
    if (comparisonRows.length) return comparisonRows;
    const providers = Array.isArray(inventory?.providers) ? inventory.providers : [];
    return providers.filter((provider) => provider.has_key || provider.provider === "ollama");
  }, [inventory]);
  const recommendations = Array.isArray(guide?.recommendations) ? guide.recommendations : [];
  const comparison = Array.isArray(guide?.openrouter_comparison) ? guide.openrouter_comparison : [];
  const rankings = Array.isArray(guide?.openrouter_rankings) ? guide.openrouter_rankings : [];
  const cloudUsage = Array.isArray(guide?.cloud_usage) ? guide.cloud_usage : [];
  const generatedAt = guide?.generated_at ? new Date(guide.generated_at).toLocaleString() : "";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-hero", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-eyebrow", children: "Reference" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { className: "md-title", children: "Model Decision Hub" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "md-subtitle", children: "Fast local guide first, live provider inventory second. Pull recommendations use machine RAM, Ollama inventory, and OpenRouter ranking signals." })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-hero-actions", children: [
        generatedAt && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-updated", children: [
          "Updated ",
          generatedAt
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "md-refresh", onClick: () => {
          refreshModelInventory(true);
          loadGuide(true);
        }, children: "Reload" })
      ] })
    ] }),
    (loadingGuide || loadingInventory) && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-state", children: "Loading model knowledge…" }),
    !loadingGuide && guideError && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-state md-state--error", children: guideError }),
    recommendations.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "md-section", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-section-head", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("h3", { className: "md-section-title", children: "What To Pull" }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-section-copy", children: [
          "Machine RAM: ",
          guide?.system_memory_gb ? `${guide.system_memory_gb} GB detected` : "unknown"
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-card-grid", children: recommendations.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("article", { className: `md-card ${item.fits_system ? "" : "md-card--dim"}`, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-card-top", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-card-title", children: item.label }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-model-cell", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `md-chip ${item.access === "cloud" ? "latest" : "cheapest"}`, children: item.access }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "md-chip best", children: item.speed }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "md-chip", children: item.cost })
            ] })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-card-side", children: item.access === "cloud" ? "No local GB" : `${Number(item.size_gb || 0).toFixed(1)} GB` })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-card-fit", children: item.fit_label }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-card-line", children: Array.isArray(item.best_for) ? item.best_for.join(" • ") : "" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-card-line", children: Array.isArray(item.agent_fit) ? `Agents: ${item.agent_fit.join(" • ")}` : "" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-card-note", children: item.notes })
      ] }, item.id)) })
    ] }),
    cloudUsage.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "md-section", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-section-head", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("h3", { className: "md-section-title", children: "Cloud Aliases In Ollama" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-section-copy", children: "How `:cloud` models like Kimi and GLM work." })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-info-grid", children: cloudUsage.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("article", { className: "md-info-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-info-title", children: item.title }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-info-copy", children: item.body })
      ] }, item.title)) })
    ] }),
    comparison.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "md-section", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-section-head", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("h3", { className: "md-section-title", children: "Cloud Comparison" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-section-copy", children: "Live-ish OpenRouter model metadata for speed/cost/context tradeoffs." })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-table-wrap", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("table", { className: "md-table", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("thead", { children: /* @__PURE__ */ jsxRuntimeExports.jsxs("tr", { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Model" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Context" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Prompt" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Completion" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Price Band" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Tools" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Vision" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Structured" })
        ] }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("tbody", { children: comparison.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("tr", { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: item.name }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: item.context_length ? `${Number(item.context_length).toLocaleString()} tok` : "—" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: priceLabel(item.prompt_price_per_million) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: priceLabel(item.completion_price_per_million) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: item.price_band || "—" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: capabilityLabel(item.supports_tools) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: capabilityLabel(item.supports_vision) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: capabilityLabel(item.supports_structured_output) })
        ] }, item.id)) })
      ] }) })
    ] }),
    rankings.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "md-section", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-section-head", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("h3", { className: "md-section-title", children: "OpenRouter Ranking Pulse" }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-section-copy", children: [
          "Source: ",
          guide?.rankings_source === "live" ? "live page" : "fallback snapshot"
        ] })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-ranking-grid", children: rankings.slice(0, 10).map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("article", { className: "md-ranking-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-ranking-top", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "md-ranking-rank", children: [
            "#",
            item.rank
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "md-ranking-share", children: item.share })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-ranking-name", children: item.name }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-ranking-author", children: item.author }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-ranking-tokens", children: [
          item.tokens,
          " weekly tokens"
        ] })
      ] }, `${item.rank}:${item.name}`)) })
    ] }),
    !loadingInventory && inventoryError && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-state md-state--error", children: "Provider inventory slow/offline. Guide still loaded." }),
    !loadingInventory && !inventoryError && rows.length === 0 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-state", children: "No configured providers yet. Add a model API key in Settings to populate provider comparison." }),
    !loadingInventory && !inventoryError && rows.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "md-section", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-section-head", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("h3", { className: "md-section-title", children: "Configured Providers" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-section-copy", children: "Live capability hints for models currently wired into Kendr." })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "md-table-wrap", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("table", { className: "md-table", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("thead", { children: /* @__PURE__ */ jsxRuntimeExports.jsxs("tr", { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Provider" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Model" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Status" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Context" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Tool Calling" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Agent Capable" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Vision" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Structured Output" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Reasoning" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Suggested Latest" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Suggested Best" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("th", { children: "Suggested Cheapest" })
        ] }) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("tbody", { children: rows.map((row, index2) => {
          const capabilities = row.model_capabilities || row.capabilities || {};
          const providerLabel = row.provider || row.model_family || row.source_provider || "—";
          const sourceProvider = row.source_provider && row.source_provider !== providerLabel ? row.source_provider : "";
          const status = row.status || (row.model_fetch_error ? `Error: ${row.model_fetch_error}` : "Ready");
          return /* @__PURE__ */ jsxRuntimeExports.jsxs("tr", { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-model-cell", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: providerLabel }),
              sourceProvider && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "md-chip", children: sourceProvider })
            ] }) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "md-model-cell", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: row.model || "—" }),
              row.selected && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "md-chip best", children: "active" }),
              !row.selected && row.configured && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "md-chip latest", children: "configured" }),
              (row.model_badges || []).map((badge) => /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `md-chip ${badge}`, children: badge }, `${providerLabel}:${row.model}:${badge}`))
            ] }) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { className: row.model_fetch_error ? "md-error-text" : "", children: status }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: row.context_window ? `${row.context_window.toLocaleString()} tokens` : "—" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: capabilityLabel(capabilities.tool_calling) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: capabilityLabel(row.agent_capable) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: capabilityLabel(capabilities.vision) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: capabilityLabel(capabilities.structured_output) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: capabilityLabel(capabilities.reasoning) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: row.suggested_latest || "—" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: row.suggested_best || "—" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: row.suggested_cheapest || "—" })
          ] }, `${providerLabel}:${row.model || row.provider}:${index2}`);
        }) })
      ] }) })
    ] })
  ] });
}
const TABS = [
  { id: "engines", label: "AI Engines" },
  { id: "workspace", label: "Workspace" },
  { id: "docs", label: "Model Docs" }
];
function SettingsHub() {
  const [tab, setTab] = reactExports.useState("engines");
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kendr-page", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card surface-card--tight", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: "Settings" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Configure AI engines, workspace preferences, and provider guidance in one place." })
      ] }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "kendr-tabs", children: TABS.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: `kendr-tab ${tab === item.id ? "active" : ""}`, onClick: () => setTab(item.id), children: item.label }, item.id)) })
    ] }),
    tab === "engines" && /* @__PURE__ */ jsxRuntimeExports.jsx(ModelManager, {}),
    tab === "workspace" && /* @__PURE__ */ jsxRuntimeExports.jsx(Settings, {}),
    tab === "docs" && /* @__PURE__ */ jsxRuntimeExports.jsx(ModelDocs, {})
  ] });
}
function formatCheckedAt(value) {
  if (!value) return "Not checked yet";
  const ts = new Date(value);
  if (Number.isNaN(ts.getTime())) return "Not checked yet";
  return ts.toLocaleString();
}
function updateFeedLabel(updateStatus) {
  if (updateStatus.feedUrl) return updateStatus.feedUrl;
  if (updateStatus.feedSource === "packaged") return "Packaged release feed";
  return "Not configured";
}
function AboutPanel() {
  const api = window.kendrAPI;
  const { state } = useApp();
  const updateStatus = state.updateStatus || {};
  const currentVersion = updateStatus.currentVersion || "unknown";
  const targetVersion = updateStatus.downloadedVersion || updateStatus.availableVersion || currentVersion;
  const downloading = updateStatus.status === "downloading";
  const checking = updateStatus.status === "checking";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "kendr-page kendr-about", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "hero-card kendr-about-hero", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "hero-copy", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "eyebrow", children: "About Kendr" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("h1", { children: "Kendr is an execution workspace for research, planning, and agent-driven work." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: "Instead of treating AI like a single chat box, Kendr gives you one surface for deep research, model routing, local file search, multi-step plans, workflow execution, and persistent run history. It is designed to move from a question to a real outcome." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "hero-actions", children: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--primary", onClick: () => api?.shell?.openExternal("https://kendr.org"), children: "Visit kendr.org" }) })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "hero-metrics", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(MetricCard, { label: "Primary role", value: "Research to execution", detail: "One workspace across discovery, planning, and delivery." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(MetricCard, { label: "Core interaction", value: "Prompt + workflow", detail: "Start in search, branch into plan, agent, or deep research." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(MetricCard, { label: "Built for", value: "Real tasks", detail: "Files, systems, tools, runs, and inspectable outputs." })
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "grid-two", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(SectionHeader, { title: "What Kendr Does", subtitle: "A practical view of the product." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutList,
          {
            items: [
              "Deep research with structured settings, citations, and source controls.",
              "Model routing across cloud and local models from the same workspace.",
              "Agent and plan modes for multi-step tasks that go beyond a single reply.",
              "Connections to files, MCP tools, integrations, and execution traces.",
              "A persistent shell where research, runs, and settings stay connected."
            ]
          }
        )
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "surface-card", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(SectionHeader, { title: "Why It Exists", subtitle: "The product intent behind Kendr." }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "kendr-about-copy", children: "Kendr is built around the idea that useful AI products should not stop at text generation. They should help users investigate, plan, act, inspect what happened, and continue from there. The goal is to turn fragmented AI interactions into a coherent working environment." })
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "surface-card", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(SectionHeader, { title: "Core Surfaces", subtitle: "The main ways Kendr is meant to be used." }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "about-grid", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutCard,
          {
            title: "Studio",
            body: "A focused orchestration surface for search-first work, research flows, planning, and model selection."
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutCard,
          {
            title: "Build",
            body: "Automation, builders, and higher-level product assembly surfaces."
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutCard,
          {
            title: "Integrations",
            body: "Connect external systems, MCP servers, and tools that agents can use."
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutCard,
          {
            title: "Runs",
            body: "Inspect execution history, workflow status, and traceable agent output."
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutCard,
          {
            title: "Memory",
            body: "Keep relevant context, project state, and reusable information close to execution."
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutCard,
          {
            title: "Settings",
            body: "Control providers, models, local engines, and environment-level behavior."
          }
        )
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "surface-card", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(SectionHeader, { title: "Creator", subtitle: "Project attribution." }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "about-creator", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "about-creator-name", children: "Prashant Dey" }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "about-creator-copy", children: [
          "Creator of Kendr. The project website is ",
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-inline-link", onClick: () => api?.shell?.openExternal("https://kendr.org"), children: "kendr.org" }),
          "."
        ] })
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "surface-card", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(SectionHeader, { title: "Desktop Updates", subtitle: "Remote application delivery for installed users." }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "about-grid", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutCard,
          {
            title: "Current Version",
            body: currentVersion
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutCard,
          {
            title: "Update Status",
            body: updateStatus.message || "Update status unavailable."
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          AboutCard,
          {
            title: "Release Feed",
            body: updateFeedLabel(updateStatus)
          }
        )
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "kendr-about-copy", children: `Target version: ${targetVersion} · Last check: ${formatCheckedAt(updateStatus.checkedAt)}` }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "hero-actions", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn kendr-btn--primary", onClick: () => api?.updates?.check(), disabled: checking, children: checking ? "Checking…" : "Check for Updates" }),
        updateStatus.status === "available" && updateStatus.autoDownload === false && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn", onClick: () => api?.updates?.download(), children: "Download Update" }),
        updateStatus.status === "downloaded" && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn", onClick: () => api?.updates?.install(), children: "Restart to Update" }),
        downloading && /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "kendr-btn", disabled: true, children: "Downloading…" })
      ] })
    ] })
  ] });
}
function SectionHeader({ title, subtitle }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "section-header", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("h2", { children: title }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("p", { children: subtitle })
  ] }) });
}
function MetricCard({ label, value, detail }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "metric-card", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "metric-card__label", children: label }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "metric-card__value", children: value }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "metric-card__detail", children: detail })
  ] });
}
function AboutCard({ title, body }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "about-card", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "about-card__title", children: title }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "about-card__body", children: body })
  ] });
}
function AboutList({ items }) {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "about-list", children: items.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "about-list__item", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "about-list__dot" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: item })
  ] }, item)) });
}
function App() {
  const { state } = useApp();
  return /* @__PURE__ */ jsxRuntimeExports.jsx(RendererErrorBoundary, { children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "app-root", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "titlebar", style: { WebkitAppRegion: "drag" }, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "titlebar-icon titlebar-icon--brand", style: { WebkitAppRegion: "no-drag" }, children: "K" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "titlebar-brand", style: { WebkitAppRegion: "no-drag" }, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "titlebar-brand__name", children: "Kendr" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "titlebar-brand__tag", children: "From research to execution" })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(MenuBar, {}),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "titlebar-center", style: { WebkitAppRegion: "drag" }, children: state.activeView !== "studio" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "titlebar-project", children: state.projectRoot ? state.projectRoot.split(/[\\/]/).pop() : "Workspace" }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(ModeSwitch, {}),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "shell-nav__status", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: `status-chip ${state.backendStatus === "running" ? "ok" : "warn"}`, children: state.backendStatus === "running" ? "Connected" : state.backendStatus }),
        state.activeView !== "studio" && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "status-chip neutral", children: state.selectedModel || "No model selected" })
      ] })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "app-body app-body--shell", children: /* @__PURE__ */ jsxRuntimeExports.jsx(RenderActiveView, {}) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(StatusBar, {}),
    state.commandPaletteOpen && /* @__PURE__ */ jsxRuntimeExports.jsx(CommandPalette, {})
  ] }) });
}
function RenderActiveView() {
  const { state, dispatch } = useApp();
  if (state.activeView === "studio") return /* @__PURE__ */ jsxRuntimeExports.jsx(StudioLayout, {});
  const titles = {
    build: "Build",
    machine: "Machine",
    memory: "Memory",
    integrations: "Integrations",
    runs: "Runs",
    marketplace: "Marketplace",
    settings: "Settings",
    developer: "Developer",
    about: "About Kendr"
  };
  const content = (() => {
    switch (state.activeView) {
      case "build":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(BuildHub, {});
      case "machine":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(MachineHub, {});
      case "memory":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(MemoryHub, {});
      case "integrations":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(IntegrationsHub, {});
      case "runs":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(AgentOrchestration, {});
      case "marketplace":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(SkillsPanel, {});
      case "settings":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(SettingsHub, {});
      case "developer":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(ProjectWorkspace, {});
      case "about":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(AboutPanel, {});
      default:
        return /* @__PURE__ */ jsxRuntimeExports.jsx(StudioLayout, {});
    }
  })();
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-shell-view", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "sl-back-bar", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { className: "sl-back-btn", onClick: () => dispatch({ type: "SET_VIEW", view: "studio" }), children: "← Back to search" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-back-title", children: titles[state.activeView] || "Workspace" })
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "sl-shell-view-body", children: content })
  ] });
}
function ModeSwitch() {
  const { state, dispatch } = useApp();
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "ms-switch", style: { WebkitAppRegion: "no-drag" }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        className: `ms-btn ${state.appMode === "studio" ? "active" : ""}`,
        onClick: () => {
          dispatch({ type: "SET_APP_MODE", mode: "studio" });
          dispatch({ type: "SET_VIEW", view: "studio" });
        },
        children: "Studio"
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        className: `ms-btn ${state.appMode === "developer" ? "active" : ""}`,
        onClick: () => {
          dispatch({ type: "SET_APP_MODE", mode: "developer" });
          dispatch({ type: "SET_VIEW", view: "developer" });
        },
        children: "Developer"
      }
    )
  ] });
}
client.createRoot(document.getElementById("root")).render(
  /* @__PURE__ */ jsxRuntimeExports.jsx(React.StrictMode, { children: /* @__PURE__ */ jsxRuntimeExports.jsx(AppProvider, { children: /* @__PURE__ */ jsxRuntimeExports.jsx(App, {}) }) })
);
export {
  getDefaultExportFromCjs as g
};
