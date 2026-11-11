/* Display-only localization. Never write translated strings into model data. */
(function (root) {
  'use strict';
  const catalog = root.PAVSIM_CATALOG;
  const storageKey = 'pavsim.language';
  const listeners = new Set();
  let language = 'en';
  try { if (root.localStorage.getItem(storageKey) === 'ru') language = 'ru'; } catch (_) { /* storage unavailable */ }
  function t(key, values = {}) {
    const text = (catalog[language] || {})[key] ?? catalog.en[key] ?? key;
    return text.replace(/\{(\w+)\}/g, (match, name) => Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match);
  }
  const escapeRE = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const patterns = Object.entries(catalog.sources).filter(([source, key]) => key.startsWith('error.') && /\{\d+\}/.test(source)).map(([source, key]) => {
    const names = [];
    const parts = source.split(/(\{\d+\})/).map(part => {
      const match = /^\{(\d+)\}$/.exec(part);
      if (match) { names.push(match[1]); return '([\\s\\S]+?)'; }
      return escapeRE(part);
    });
    return {key, names, regex: new RegExp('^' + parts.join('') + '$'), specificity: source.replace(/\{\d+\}/g, '').length};
  }).sort((a,b) => b.specificity-a.specificity);
  function message(value, depth = 0) {
    const text = String(value);
    if (depth > 6) return text;
    if (catalog.sources[text]) return t(catalog.sources[text]);
    // repr() wrappers are diagnostics, not identifiers or model data.
    const wrapper = /^(\w+(?:Error|Exception))\((['"])([\s\S]*)\2\)$/.exec(text);
    if (wrapper) return wrapper[1] + ': ' + message(wrapper[3], depth+1);
    for (const pattern of patterns) {
      const match = pattern.regex.exec(text);
      if (!match) continue;
      const values = {};
      pattern.names.forEach((name,i) => { values[name] = match[i+1]; });
      if (['error.compute_failed','error.derivative_failed','error.parameters_failed','error.memory_failed','error.no_run'].includes(pattern.key)) {
        const last = pattern.names[pattern.names.length-1];
        values[last] = message(values[last], depth+1);
      }
      if (['error.number','error.finite','error.finite_bool','error.range_type','error.range_value'].includes(pattern.key)) values[0]=message(values[0],depth+1);
      return t(pattern.key, values);
    }
    return text; // Preserve unknown custom-block/OS diagnostics verbatim.
  }
  function blockName(bt) { const key = 'block.'+bt.name+'.name'; return catalog.en[key] ? t(key) : bt.display_name || bt.name; }
  function blockDescription(bt) { const key = 'block.'+bt.name+'.description'; return catalog.en[key] ? t(key) : bt.description || ''; }
  function parameter(key) { return catalog.en['param.'+key] ? t('param.'+key) : key; }
  function port(label) { return message(label); }
  function plotLabel(value) {
    const text=String(value);
    const key=catalog.sources[text];
    return key && (key==='port.signal' || key.startsWith('legacy.') || /^block\.graph_.*\.name$/.test(key)) ? t(key) : text;
  }
  function apply(container = root.document) {
    if (!container) return;
    if (root.document.documentElement) root.document.documentElement.lang = language;
    container.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    container.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); });
    container.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    const selector = root.document.getElementById('language');
    if (selector) { selector.value = language; if(selector.setAttribute)selector.setAttribute('aria-label',t('ui.language')); }
  }
  function setLanguage(next, persist = true) {
    language = next === 'ru' ? 'ru' : 'en';
    if (persist) { try { root.localStorage.setItem(storageKey, language); } catch (_) { /* private mode */ } }
    apply();
    listeners.forEach(listener => listener(language));
  }
  root.I18n = {t, message, blockName, blockDescription, parameter, port, plotLabel, apply, setLanguage,
    get language() { return language; }, onChange(listener) { listeners.add(listener); }};
  if (root.window) root.window.addEventListener('storage', event => {
    if (event.key === storageKey) setLanguage(event.newValue, false);
  });
})(globalThis);
