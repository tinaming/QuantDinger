/**
 * @license
 * Copyright 2019 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */const C=Symbol("Comlink.proxy"),z=Symbol("Comlink.endpoint"),L=Symbol("Comlink.releaseProxy"),j=Symbol("Comlink.finalizer"),w=Symbol("Comlink.thrown"),T=t=>typeof t=="object"&&t!==null||typeof t=="function",D={canHandle:t=>T(t)&&t[C],serialize(t){const{port1:e,port2:n}=new MessageChannel;return S(t,e),[n,[n]]},deserialize(t){return t.start(),W(t)}},V={canHandle:t=>T(t)&&w in t,serialize({value:t}){let e;return t instanceof Error?e={isError:!0,value:{message:t.message,name:t.name,stack:t.stack}}:e={isError:!1,value:t},[e,[]]},deserialize(t){throw t.isError?Object.assign(new Error(t.value.message),t.value):t.value}},M=new Map([["proxy",D],["throw",V]]);function H(t,e){for(const n of t)if(e===n||n==="*"||n instanceof RegExp&&n.test(e))return!0;return!1}function S(t,e=globalThis,n=["*"]){e.addEventListener("message",function f(r){if(!r||!r.data)return;if(!H(n,r.origin)){console.warn(`Invalid origin '${r.origin}' for comlink proxy`);return}const{id:i,type:_,path:c}=Object.assign({path:[]},r.data),l=(r.data.argumentList||[]).map(p);let a;try{const o=c.slice(0,-1).reduce((u,g)=>u[g],t),d=c.reduce((u,g)=>u[g],t);switch(_){case"GET":a=d;break;case"SET":o[c.slice(-1)[0]]=p(r.data.value),a=!0;break;case"APPLY":a=d.apply(o,l);break;case"CONSTRUCT":{const u=new d(...l);a=Y(u)}break;case"ENDPOINT":{const{port1:u,port2:g}=new MessageChannel;S(t,g),a=G(u,[u])}break;case"RELEASE":a=void 0;break;default:return}}catch(o){a={value:o,[w]:0}}Promise.resolve(a).catch(o=>({value:o,[w]:0})).then(o=>{const[d,u]=x(o);e.postMessage(Object.assign(Object.assign({},d),{id:i}),u),_==="RELEASE"&&(e.removeEventListener("message",f),O(e),j in t&&typeof t[j]=="function"&&t[j]())}).catch(o=>{const[d,u]=x({value:new TypeError("Unserializable return value"),[w]:0});e.postMessage(Object.assign(Object.assign({},d),{id:i}),u)})}),e.start&&e.start()}function I(t){return t.constructor.name==="MessagePort"}function O(t){I(t)&&t.close()}function W(t,e){const n=new Map;return t.addEventListener("message",function(r){const{data:i}=r;if(!i||!i.id)return;const _=n.get(i.id);if(_)try{_(i)}finally{n.delete(i.id)}}),k(t,n,[],e)}function h(t){if(t)throw new Error("Proxy has been released and is not useable")}function v(t){return y(t,new Map,{type:"RELEASE"}).then(()=>{O(t)})}const E=new WeakMap,P="FinalizationRegistry"in globalThis&&new FinalizationRegistry(t=>{const e=(E.get(t)||0)-1;E.set(t,e),e===0&&v(t)});function F(t,e){const n=(E.get(e)||0)+1;E.set(e,n),P&&P.register(t,e,t)}function U(t){P&&P.unregister(t)}function k(t,e,n=[],f=function(){}){let r=!1;const i=new Proxy(f,{get(_,c){if(h(r),c===L)return()=>{U(i),v(t),e.clear(),r=!0};if(c==="then"){if(n.length===0)return{then:()=>i};const l=y(t,e,{type:"GET",path:n.map(a=>a.toString())}).then(p);return l.then.bind(l)}return k(t,e,[...n,c])},set(_,c,l){h(r);const[a,o]=x(l);return y(t,e,{type:"SET",path:[...n,c].map(d=>d.toString()),value:a},o).then(p)},apply(_,c,l){h(r);const a=n[n.length-1];if(a===z)return y(t,e,{type:"ENDPOINT"}).then(p);if(a==="bind")return k(t,e,n.slice(0,-1));const[o,d]=R(l);return y(t,e,{type:"APPLY",path:n.map(u=>u.toString()),argumentList:o},d).then(p)},construct(_,c){h(r);const[l,a]=R(c);return y(t,e,{type:"CONSTRUCT",path:n.map(o=>o.toString()),argumentList:l},a).then(p)}});return F(i,t),i}function B(t){return Array.prototype.concat.apply([],t)}function R(t){const e=t.map(x);return[e.map(n=>n[0]),B(e.map(n=>n[1]))]}const N=new WeakMap;function G(t,e){return N.set(t,e),t}function Y(t){return Object.assign(t,{[C]:!0})}function x(t){for(const[e,n]of M)if(n.canHandle(t)){const[f,r]=n.serialize(t);return[{type:"HANDLER",name:e,value:f},r]}return[{type:"RAW",value:t},N.get(t)||[]]}function p(t){switch(t.type){case"HANDLER":return M.get(t.name).deserialize(t.value);case"RAW":return t.value}}function y(t,e,n,f){return new Promise(r=>{const i=$();e.set(i,r),t.start&&t.start(),t.postMessage(Object.assign({id:i},n),f)})}function $(){return new Array(4).fill(0).map(()=>Math.floor(Math.random()*Number.MAX_SAFE_INTEGER).toString(16)).join("-")}let s=null,m=null,b=null;const A=t=>(t&&!t.endsWith("/")?t+"/":t)||t;async function J(t){const n=await(await import(`${t}pyodide.mjs`)).loadPyodide({indexURL:t});return await n.loadPackage(["pandas","numpy"]),n}async function q(t={}){if(s)return{ok:!0};if(m)return m;const e=t.version||"0.25.0",n=`https://cdn.jsdelivr.net/pyodide/v${e}/full/`,f=`/assets/pyodide/v${e}/full/`,r=A(t.cdnBase||n),i=A(t.localBase||f),c=(t.preferCdn!==void 0?!!t.preferCdn:!0)?[r,i]:[i,r];return m=(async()=>{let l=null;for(const a of c)try{return s=await J(a),{ok:!0,baseUrl:a}}catch(o){l=o}throw b=l,m=null,l||new Error("Pyodide 初始化失败：所有候选源均不可用")})(),m}async function X(t=[]){if(!s)throw new Error("Pyodide 未初始化");t.length&&await s.loadPackage(t)}async function K(t,e={}){if(!s)throw new Error("Pyodide 未初始化");for(const[f,r]of Object.entries(e))s.globals.set(f,r);const n=await s.runPythonAsync(t);if(n&&typeof n=="object"&&typeof n.toJs=="function")try{return n.toJs()}finally{try{n.destroy()}catch{}}return n}const Q=`
import json
import pandas as pd
import numpy as np

def _clean_nan(obj):
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(item) for item in obj]
    if isinstance(obj, (pd.Series, np.ndarray)):
        return [None if (isinstance(x, float) and (np.isnan(x) or np.isinf(x))) else x for x in obj]
    if isinstance(obj, (float, np.floating)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return obj


_raw = raw_data.to_py() if hasattr(raw_data, 'to_py') else raw_data
_params = params.to_py() if hasattr(params, 'to_py') else params


def _get_param(key, default=None):
    if key in _params:
        return _params.get(key, default)
    camel = ''.join([key.split('_')[0]] + [p.capitalize() for p in key.split('_')[1:]])
    return _params.get(camel, default)


try:
    leverage = float(_get_param('leverage', 1) or 1)
except Exception:
    leverage = 1

trade_direction = _get_param('trade_direction', _get_param('tradeDirection', 'both')) or 'both'

def _safe_int(name, default=0):
    try:
        return int(_get_param(name, default) or default)
    except Exception:
        return default

def _safe_float(name, default=0.0):
    try:
        return float(_get_param(name, default) or default)
    except Exception:
        return default

initial_position = _safe_int('initial_position', 0)
initial_avg_entry_price = _safe_float('initial_avg_entry_price', 0.0)
initial_position_count = _safe_int('initial_position_count', 0)
initial_last_add_price = _safe_float('initial_last_add_price', 0.0)
initial_highest_price = _safe_float('initial_highest_price', 0.0)

df = pd.DataFrame(_raw)
for col in ('open', 'high', 'low', 'close', 'volume'):
    if col in df.columns:
        df[col] = df[col].astype(float)

_local_ns = {
    'df': df,
    'pd': pd,
    'np': np,
    'json': json,
    'leverage': leverage,
    'trade_direction': trade_direction,
    'initial_position': initial_position,
    'initial_avg_entry_price': initial_avg_entry_price,
    'initial_position_count': initial_position_count,
    'initial_last_add_price': initial_last_add_price,
    'initial_highest_price': initial_highest_price,
    'params': _params,
}

exec(user_code, _local_ns, _local_ns)

if 'output' not in _local_ns:
    if 'result_json' in _local_ns:
        output = json.loads(_local_ns['result_json'])
    else:
        output = {"plots": []}
else:
    output = _local_ns['output']
    if isinstance(output, str):
        output = json.loads(output)

output = _clean_nan(output)
json.dumps(output)
`;async function Z({userCode:t,rawData:e,params:n}){if(!s)throw new Error("Pyodide 未初始化");s.globals.set("user_code",t),s.globals.set("raw_data",e||[]),s.globals.set("params",n||{});try{return await s.runPythonAsync(Q)}finally{s.globals.set("user_code",""),s.globals.set("raw_data",null),s.globals.set("params",null)}}function tt(){return{ready:!!s,error:b?String(b.message||b):null}}S({init:q,runPython:K,runStrategy:Z,loadPackages:X,status:tt});
