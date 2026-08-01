#!/usr/bin/env python3
"""Patch Login SPA bundle: stop false '请输入验证码' when Send Code fails."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
LOGIN = ROOT / "html" / "assets" / "Login-NPueRW5a.js"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text or (label.startswith("idempotent:") and text.count(label.split(":", 1)[-1]) > 0):
            print(f"  SKIP (already applied): {label}")
            return text
        print(f"  MISS: {label}: {old[:90]!r}")
        return text
    if count > 1:
        print(f"  WARN: {count} matches for {label}, replacing all")
    print(f"  OK: {count}x {label}")
    return text.replace(old, new)


def main() -> int:
    if not LOGIN.exists():
        print(f"missing {LOGIN}", file=sys.stderr)
        return 1

    text = LOGIN.read_text(encoding="utf-8")
    original = text

    # Code fields: do not validate-on-blur when Send is clicked.
    for key in ("user.login.codeRequired", "user.register.codeRequired", "user.resetPassword.codeRequired"):
        old = f'value:["code",{{rules:[{{required:!0,message:e.$t("{key}")||"Please enter verification code"}}],validateTrigger:"blur"}}]'
        new = f'value:["code",{{rules:[{{required:!0,message:e.$t("{key}")||"Please enter verification code"}}],validateTrigger:[]}}]'
        text = _replace_once(text, old, new, key)

    # Prevent Send from submitting the form (which would validate empty code).
    text = _replace_once(
        text,
        'attrs:{size:"large",block:"",loading:e.codeLoginSendingCode,disabled:e.codeLoginSendingCode||e.codeLoginCountdown>0||e.securityConfig.turnstile_enabled&&!e.codeLoginTurnstileToken}',
        'attrs:{size:"large",block:"",htmlType:"button",loading:e.codeLoginSendingCode,disabled:e.codeLoginSendingCode||e.codeLoginCountdown>0||e.securityConfig.turnstile_enabled&&!e.codeLoginTurnstileToken}',
        "send-btn-code-login",
    )
    text = _replace_once(
        text,
        'attrs:{size:"large",block:"",loading:e.registerSendingCode,disabled:e.registerSendingCode||e.registerCountdown>0||e.securityConfig.turnstile_enabled&&!e.registerTurnstileToken}',
        'attrs:{size:"large",block:"",htmlType:"button",loading:e.registerSendingCode,disabled:e.registerSendingCode||e.registerCountdown>0||e.securityConfig.turnstile_enabled&&!e.registerTurnstileToken}',
        "send-btn-register",
    )
    text = _replace_once(
        text,
        'attrs:{size:"large",block:"",loading:e.resetSendingCode,disabled:e.resetSendingCode||e.resetCountdown>0||e.securityConfig.turnstile_enabled&&!e.resetTurnstileToken}',
        'attrs:{size:"large",block:"",htmlType:"button",loading:e.resetSendingCode,disabled:e.resetSendingCode||e.resetCountdown>0||e.securityConfig.turnstile_enabled&&!e.resetTurnstileToken}',
        "send-btn-reset",
    )

    # Clear stale code-field errors before send.
    text = _replace_once(
        text,
        'async handleCodeLoginSendCode(){this.codeLoginForm.validateFields(["email"],',
        'async handleCodeLoginSendCode(){this.codeLoginForm.setFields({code:{value:this.codeLoginForm.getFieldValue("code")||"",errors:undefined}}),this.codeLoginForm.validateFields(["email"],',
        "handler-code-login",
    )
    text = _replace_once(
        text,
        'async handleRegisterSendCode(){this.registerForm.validateFields(["email"],',
        'async handleRegisterSendCode(){this.registerForm.setFields({code:{value:this.registerForm.getFieldValue("code")||"",errors:undefined}}),this.registerForm.validateFields(["email"],',
        "handler-register",
    )
    text = _replace_once(
        text,
        'async handleResetSendCode(){this.resetForm.validateFields(["email"],',
        'async handleResetSendCode(){this.resetForm.setFields({code:{value:this.resetForm.getFieldValue("code")||"",errors:undefined}}),this.resetForm.validateFields(["email"],',
        "handler-reset",
    )

    timeout_msg = (
        'catch(t){const r=t&&t.response&&t.response.data&&t.response.data.msg;'
        'this.CODE_ERROR=r||(t&&(t.code==="ECONNABORTED"||/timeout/i.test(String(t.message||"")))'
        '?"Request timed out. Server may be busy — please retry.":"Failed to send code")}'
    )
    for err_attr in ("codeLoginError", "registerError", "resetError"):
        old = f'catch(t){{this.{err_attr}=t.response?.data?.msg||"Failed to send code"}}'
        new = timeout_msg.replace("CODE_ERROR", err_attr)
        text = _replace_once(text, old, new, f"catch-{err_attr}")

    if text == original:
        print("No changes needed (already patched)")
        return 0

    LOGIN.write_text(text, encoding="utf-8")
    print(f"Patched {LOGIN.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
