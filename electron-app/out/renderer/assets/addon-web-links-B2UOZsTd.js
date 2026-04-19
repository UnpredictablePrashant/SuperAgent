import { g as getDefaultExportFromCjs } from "./index-Dxp5xSiv.js";
function _mergeNamespaces(n, m) {
  for (var i = 0; i < m.length; i++) {
    const e = m[i];
    if (typeof e !== "string" && !Array.isArray(e)) {
      for (const k in e) {
        if (k !== "default" && !(k in n)) {
          const d = Object.getOwnPropertyDescriptor(e, k);
          if (d) {
            Object.defineProperty(n, k, d.get ? d : {
              enumerable: true,
              get: () => e[k]
            });
          }
        }
      }
    }
  }
  return Object.freeze(Object.defineProperty(n, Symbol.toStringTag, { value: "Module" }));
}
var addonWebLinks$1 = { exports: {} };
(function(module, exports$1) {
  !function(e, t) {
    module.exports = t();
  }(self, () => (() => {
    var e = { 6: (e2, t2) => {
      function n2(e3) {
        try {
          const t3 = new URL(e3), n3 = t3.password && t3.username ? `${t3.protocol}//${t3.username}:${t3.password}@${t3.host}` : t3.username ? `${t3.protocol}//${t3.username}@${t3.host}` : `${t3.protocol}//${t3.host}`;
          return e3.toLocaleLowerCase().startsWith(n3.toLocaleLowerCase());
        } catch (e4) {
          return false;
        }
      }
      Object.defineProperty(t2, "__esModule", { value: true }), t2.LinkComputer = t2.WebLinkProvider = void 0, t2.WebLinkProvider = class {
        constructor(e3, t3, n3, o3 = {}) {
          this._terminal = e3, this._regex = t3, this._handler = n3, this._options = o3;
        }
        provideLinks(e3, t3) {
          const n3 = o2.computeLink(e3, this._regex, this._terminal, this._handler);
          t3(this._addCallbacks(n3));
        }
        _addCallbacks(e3) {
          return e3.map((e4) => (e4.leave = this._options.leave, e4.hover = (t3, n3) => {
            if (this._options.hover) {
              const { range: o3 } = e4;
              this._options.hover(t3, n3, o3);
            }
          }, e4));
        }
      };
      class o2 {
        static computeLink(e3, t3, r, i) {
          const s = new RegExp(t3.source, (t3.flags || "") + "g"), [a, c] = o2._getWindowedLineStrings(e3 - 1, r), l = a.join("");
          let d;
          const p = [];
          for (; d = s.exec(l); ) {
            const e4 = d[0];
            if (!n2(e4)) continue;
            const [t4, s2] = o2._mapStrIdx(r, c, 0, d.index), [a2, l2] = o2._mapStrIdx(r, t4, s2, e4.length);
            if (-1 === t4 || -1 === s2 || -1 === a2 || -1 === l2) continue;
            const h = { start: { x: s2 + 1, y: t4 + 1 }, end: { x: l2, y: a2 + 1 } };
            p.push({ range: h, text: e4, activate: i });
          }
          return p;
        }
        static _getWindowedLineStrings(e3, t3) {
          let n3, o3 = e3, r = e3, i = 0, s = "";
          const a = [];
          if (n3 = t3.buffer.active.getLine(e3)) {
            const e4 = n3.translateToString(true);
            if (n3.isWrapped && " " !== e4[0]) {
              for (i = 0; (n3 = t3.buffer.active.getLine(--o3)) && i < 2048 && (s = n3.translateToString(true), i += s.length, a.push(s), n3.isWrapped && -1 === s.indexOf(" ")); ) ;
              a.reverse();
            }
            for (a.push(e4), i = 0; (n3 = t3.buffer.active.getLine(++r)) && n3.isWrapped && i < 2048 && (s = n3.translateToString(true), i += s.length, a.push(s), -1 === s.indexOf(" ")); ) ;
          }
          return [a, o3];
        }
        static _mapStrIdx(e3, t3, n3, o3) {
          const r = e3.buffer.active, i = r.getNullCell();
          let s = n3;
          for (; o3; ) {
            const e4 = r.getLine(t3);
            if (!e4) return [-1, -1];
            for (let n4 = s; n4 < e4.length; ++n4) {
              e4.getCell(n4, i);
              const s2 = i.getChars();
              if (i.getWidth() && (o3 -= s2.length || 1, n4 === e4.length - 1 && "" === s2)) {
                const e5 = r.getLine(t3 + 1);
                e5 && e5.isWrapped && (e5.getCell(0, i), 2 === i.getWidth() && (o3 += 1));
              }
              if (o3 < 0) return [t3, n4];
            }
            t3++, s = 0;
          }
          return [t3, s];
        }
      }
      t2.LinkComputer = o2;
    } }, t = {};
    function n(o2) {
      var r = t[o2];
      if (void 0 !== r) return r.exports;
      var i = t[o2] = { exports: {} };
      return e[o2](i, i.exports, n), i.exports;
    }
    var o = {};
    return (() => {
      var e2 = o;
      Object.defineProperty(e2, "__esModule", { value: true }), e2.WebLinksAddon = void 0;
      const t2 = n(6), r = /(https?|HTTPS?):[/]{2}[^\s"'!*(){}|\\\^<>`]*[^\s"':,.!?{}|\\\^~\[\]`()<>]/;
      function i(e3, t3) {
        const n2 = window.open();
        if (n2) {
          try {
            n2.opener = null;
          } catch {
          }
          n2.location.href = t3;
        } else console.warn("Opening link blocked as opener could not be cleared");
      }
      e2.WebLinksAddon = class {
        constructor(e3 = i, t3 = {}) {
          this._handler = e3, this._options = t3;
        }
        activate(e3) {
          this._terminal = e3;
          const n2 = this._options, o2 = n2.urlRegex || r;
          this._linkProvider = this._terminal.registerLinkProvider(new t2.WebLinkProvider(this._terminal, o2, this._handler, n2));
        }
        dispose() {
          this._linkProvider?.dispose();
        }
      };
    })(), o;
  })());
})(addonWebLinks$1);
var addonWebLinksExports = addonWebLinks$1.exports;
const addonWebLinks_default = /* @__PURE__ */ getDefaultExportFromCjs(addonWebLinksExports);
const addonWebLinks = /* @__PURE__ */ _mergeNamespaces({
  __proto__: null,
  default: addonWebLinks_default
}, [addonWebLinksExports]);
export {
  addonWebLinks as a
};
