"""Telegram 수신 데몬 — 백그라운드 스레드에서 long polling."""

from __future__ import annotations

import threading
from typing import Optional

import httpx

from ..config import ForgeConfig, ProjectPaths

_API_BASE = "https://api.telegram.org"


class TelegramReceiver:
    """getUpdates 폴링, 명령어와 파일을 시그널 파일로 변환."""

    def __init__(self, config: ForgeConfig, paths: ProjectPaths):
        self.config = config
        self.paths = paths
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_update_id = 0

    def start(self) -> None:
        if not self.config.telegram_enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _base_url(self) -> str:
        return f"{_API_BASE}/bot{self.config.telegram_bot_token}"

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                with httpx.Client(timeout=35.0) as client:
                    resp = client.get(
                        f"{self._base_url()}/getUpdates",
                        params={
                            "offset": self._last_update_id + 1,
                            "timeout": 25,
                        },
                    )
                if resp.status_code != 200:
                    self._stop.wait(timeout=2)
                    continue
                for update in resp.json().get("result", []):
                    self._last_update_id = update["update_id"]
                    self._handle_update(update)
            except httpx.HTTPError:
                self._stop.wait(timeout=3)
            except Exception:
                self._stop.wait(timeout=3)

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or update.get("channel_post") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id and chat_id != str(self.config.telegram_chat_id):
            return
        text = message.get("text", "") or message.get("caption", "") or ""
        if text.startswith("/"):
            self._handle_command(text.strip())
        doc = message.get("document")
        if doc:
            self._handle_file(doc, message.get("caption", ""))

    def _handle_command(self, text: str) -> None:
        cmd = text.split(maxsplit=1)[0].lower()
        self.paths.ensure_artifacts()
        if cmd in ("/resume", "/approve", "/계속", "/진행"):
            self.paths.approval_signal.write_text("resume\n", encoding="utf-8")
        elif cmd in ("/skip", "/스킵", "/무시"):
            self.paths.skip_signal.write_text("skip\n", encoding="utf-8")
            self.paths.approval_signal.write_text("skip\n", encoding="utf-8")
        elif cmd == "/continue":
            self.paths.continue_signal.write_text("continue\n", encoding="utf-8")
        elif cmd in ("/exit", "/종료"):
            self.paths.exit_signal.write_text("exit\n", encoding="utf-8")
        elif cmd in ("/eval", "/재평가"):
            self.paths.eval_signal.write_text("eval\n", encoding="utf-8")
        elif cmd in ("/stop", "/중단"):
            self.paths.stop_signal.write_text("stop\n", encoding="utf-8")
        elif cmd in ("/status", "/상태"):
            self._send_status()
        elif cmd in ("/help", "/도움"):
            self._send_help()

    def _handle_file(self, doc: dict, caption: str) -> None:
        """caption이 'artifacts/...' 형식이면 해당 경로에 저장 (traversal 검증)."""
        if not caption.startswith("artifacts/"):
            return
        rel = caption[len("artifacts/") :].strip()
        if not rel:
            return
        target = (self.paths.artifacts / rel).resolve()
        try:
            target.relative_to(self.paths.artifacts.resolve())
        except ValueError:
            return

        self.paths.backup.mkdir(parents=True, exist_ok=True)
        if target.exists():
            backup_path = self.paths.backup / f"{target.name}.bak"
            try:
                target.replace(backup_path)
            except OSError:
                pass

        try:
            with httpx.Client(timeout=30.0) as client:
                info = client.get(
                    f"{self._base_url()}/getFile",
                    params={"file_id": doc["file_id"]},
                ).json()
                file_path = info["result"]["file_path"]
                resp = client.get(
                    f"{_API_BASE}/file/bot{self.config.telegram_bot_token}/{file_path}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(resp.content)
            self._reply(f"✅ {caption} 저장 완료")
        except (httpx.HTTPError, KeyError, OSError):
            self._reply(f"❌ {caption} 저장 실패")

    def _send_status(self) -> None:
        from ..checkpoint import Checkpoint
        from ..cost_tracker import parse_cost_log

        cp = Checkpoint.load(self.paths.checkpoint_file)
        total_mins = parse_cost_log(self.paths.cost_log)
        self._reply(
            f"📊 [{self.paths.project_name}]\n"
            f"Phase: {cp.phase.name}\n"
            f"Sprint: #{self.paths.current_sprint()}\n"
            f"누적 시간: {total_mins:.0f}분\n"
            f"Detail: {cp.detail}\n"
            f"Updated: {cp.timestamp}"
        )

    def _send_help(self) -> None:
        self._reply(
            "📖 사용 가능한 명령어:\n"
            "/resume — 다음 단계 진행\n"
            "/eval — Evaluator만 재실행 (FAIL 시)\n"
            "/stop — 자동 루프 중단\n"
            "/skip — 현재 단계 건너뜀\n"
            "/status — 현재 상태 조회\n"
            "/exit — 즉시 종료\n"
            "/help — 이 도움말"
        )

    def _reply(self, text: str) -> None:
        try:
            with httpx.Client(timeout=10.0) as client:
                client.post(
                    f"{self._base_url()}/sendMessage",
                    data={"chat_id": self.config.telegram_chat_id, "text": text[:4096]},
                )
        except httpx.HTTPError:
            pass
