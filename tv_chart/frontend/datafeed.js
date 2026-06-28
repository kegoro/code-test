// JavaScript datafeed adapter for the TradingView Charting Library.
// Wraps our FastAPI UDF endpoints behind the JsAPI surface TV expects.
//
// Reference: TradingView Charting Library docs → "JavaScript API".

(function (global) {
  'use strict';

  const SUPPORTED_RESOLUTIONS = ['1', '3', '1D'];

  function udfUrl(path, params) {
    const usp = new URLSearchParams(params || {});
    const qs = usp.toString();
    return '/datafeed' + path + (qs ? '?' + qs : '');
  }

  async function json(url) {
    const resp = await fetch(url, { credentials: 'same-origin' });
    if (!resp.ok) throw new Error('HTTP ' + resp.status + ' for ' + url);
    return resp.json();
  }

  class SMCDatafeed {
    constructor() {
      this._subscriptions = new Map();
    }

    // Required: TV calls this exactly once when the chart inits.
    onReady(callback) {
      json(udfUrl('/config')).then(cfg => {
        setTimeout(() => callback(cfg), 0);
      }).catch(err => {
        console.error('onReady config failed:', err);
        setTimeout(() => callback({
          supported_resolutions: SUPPORTED_RESOLUTIONS,
          supports_search: true,
          supports_marks: true,
          supports_time: true,
        }), 0);
      });
    }

    // Required: substring symbol search.
    searchSymbols(userInput, exchange, symbolType, onResult) {
      json(udfUrl('/search', {
        query: userInput,
        exchange: exchange || '',
        type: symbolType || '',
        limit: 30,
      }))
      .then(onResult)
      .catch(err => {
        console.error('searchSymbols failed:', err);
        onResult([]);
      });
    }

    // Required: resolve a symbol code → SymbolInfo object.
    resolveSymbol(symbolName, onResolve, onError) {
      json(udfUrl('/symbols', { symbol: symbolName }))
        .then(info => setTimeout(() => onResolve(info), 0))
        .catch(err => onError(err.message || String(err)));
    }

    // Required: fetch historical bars.
    // periodParams = { from, to, countBack, firstDataRequest }
    getBars(symbolInfo, resolution, periodParams, onResult, onError) {
      const params = {
        symbol: symbolInfo.ticker || symbolInfo.name,
        resolution: resolution,
        from: periodParams.from,
        to: periodParams.to,
      };
      json(udfUrl('/history', params))
        .then(res => {
          if (res.s === 'no_data') {
            onResult([], { noData: true, nextTime: res.nextTime });
            return;
          }
          if (res.s !== 'ok') {
            onError(res.errmsg || 'datafeed error');
            return;
          }
          const bars = res.t.map((t, i) => ({
            time: t * 1000,           // TV expects ms
            open: res.o[i],
            high: res.h[i],
            low:  res.l[i],
            close:res.c[i],
            volume: res.v[i],
          }));
          onResult(bars, { noData: bars.length === 0 });
        })
        .catch(err => onError(err.message || String(err)));
    }

    // Optional but recommended: visible-range SMC annotations.
    getMarks(symbolInfo, from, to, onDataCallback, resolution) {
      json(udfUrl('/marks', {
        symbol: symbolInfo.ticker || symbolInfo.name,
        resolution: resolution,
        from: from,
        to: to,
      }))
      .then(payload => {
        // UDF column-major → TV row-major
        if (!payload || !payload.time || payload.time.length === 0) {
          onDataCallback([]);
          return;
        }
        const rows = payload.time.map((t, i) => ({
          id: payload.id[i],
          time: t,
          color: payload.color[i],
          text: payload.text[i],
          label: payload.label[i],
          labelFontColor: payload.labelFontColor[i],
          minSize: payload.minSize[i],
        }));
        onDataCallback(rows);
      })
      .catch(err => {
        console.warn('getMarks failed:', err);
        onDataCallback([]);
      });
    }

    // Required for streaming. Stub now — Shioaji push will land here later.
    subscribeBars(symbolInfo, resolution, onTick, listenerGuid, onResetCache) {
      this._subscriptions.set(listenerGuid, { symbolInfo, resolution, onTick });
    }

    unsubscribeBars(listenerGuid) {
      this._subscriptions.delete(listenerGuid);
    }

    // Optional: server clock so TV can detect drift.
    getServerTime(callback) {
      json(udfUrl('/time'))
        .then(t => callback(t))
        .catch(() => callback(Math.floor(Date.now() / 1000)));
    }
  }

  global.SMCDatafeed = SMCDatafeed;
}(window));
