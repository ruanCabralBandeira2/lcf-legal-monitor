from __future__ import annotations

import argparse
import contextlib
import getpass
import importlib.util
import json
import platform
import re
import sys
import tempfile
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from legal_monitor import __version__
from legal_monitor.admin.portfolio import parse_portfolio
from legal_monitor.admin.repository import AdminRepositoryError, PostgresAdminRepository
from legal_monitor.admin.service import AdminService, AdminValidationError
from legal_monitor.browser.session import BrowserSessionManager, BrowserUnavailableError
from legal_monitor.config import ConfigError, Settings
from legal_monitor.connectors.eproc import EprocConnector
from legal_monitor.connectors.errors import ConnectorError
from legal_monitor.connectors.fake import FakeConnector
from legal_monitor.connectors.routing import (
    CATALOG,
    SourceEndpoint,
    UnknownSourceError,
    candidate_keys,
    candidate_sources,
    get_endpoint,
)
from legal_monitor.documents.service import DocumentService, DocumentValidationError
from legal_monitor.domain.cnj import CnjNumber, InvalidCnjNumber
from legal_monitor.domain.enums import Sensitivity, SessionState, SourceSystem
from legal_monitor.domain.models import Movement, ProcessRef
from legal_monitor.monitoring.auth_alert import AuthAlertService, build_approval_message
from legal_monitor.monitoring.latest import LatestMovementService
from legal_monitor.monitoring.monitor import MonitorService, connector_for, next_candidate
from legal_monitor.monitoring.monitor_repository import PostgresMonitorRepository
from legal_monitor.monitoring.repository import PostgresManualActionStore
from legal_monitor.notifications.base import NotificationAttachment, NotificationMessage
from legal_monitor.notifications.discord import (
    DiscordNotificationError,
    DiscordWebhookNotifier,
)
from legal_monitor.notifications.email import (
    EmailNotificationError,
    EmailNotifier,
    SmtpSslTransport,
)
from legal_monitor.notifications.fake import FakeNotifier
from legal_monitor.notifications.keychain import KeychainSecretError, MacOSKeychainSecretProvider
from legal_monitor.scheduler.policy import RetryPolicy
from legal_monitor.scheduler.repository import PostgresSchedulerRepository
from legal_monitor.scheduler.worker import SchedulerWorker
from legal_monitor.secrets import KeyringSecretStore, SecretStoreError
from legal_monitor.summaries.fake import FAKE_EXTRACTED_DOCUMENT, FakeSummaryProvider
from legal_monitor.summaries.service import SummaryService


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def doctor() -> int:
    checks: dict[str, Any] = {
        "version": __version__,
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "pypdf": importlib.util.find_spec("pypdf") is not None,
        "psycopg": importlib.util.find_spec("psycopg") is not None,
        "keyring": importlib.util.find_spec("keyring") is not None,
        "playwright": importlib.util.find_spec("playwright") is not None,
    }
    try:
        settings = Settings.from_env()
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.temp_dir):
            pass
        checks.update(
            {
                "configuration": "valid",
                "environment": settings.app_env.value,
                "storage_writable": True,
                "real_connectors_enabled": settings.real_connectors_enabled,
                "whatsapp_enabled": settings.whatsapp_enabled,
                "discord_demo_enabled": settings.discord_demo_enabled,
                "discord_secret_store": "macos-keychain",
                "m0_approved": settings.m0_approved,
                "summary_enabled": settings.summary_enabled,
                "email_enabled": settings.email_enabled,
                "email_recipients": {
                    "lawyer": len(settings.email_lawyer_to),
                    "operator": len(settings.email_operator_to),
                },
                "browser_channel": settings.browser_channel or "chromium",
            }
        )
    except (ConfigError, OSError) as exc:
        checks.update({"configuration": "invalid", "error": str(exc)})
        _emit(checks)
        return 1
    _emit(checks)
    return 0


def validate_cnj(value: str) -> int:
    try:
        cnj = CnjNumber.parse(value)
    except InvalidCnjNumber as exc:
        _emit({"valid": False, "error": str(exc)})
        return 1
    _emit({"valid": True, "formatted": str(cnj), "masked": cnj.masked()})
    return 0


def _example_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def demo() -> int:
    settings = Settings.from_env(environ={"APP_ENV": "test"}, load_dotenv=False)
    cnj = CnjNumber.from_components(
        sequence=1,
        year=2026,
        justice=8,
        tribunal=19,
        origin=1,
    )
    process = ProcessRef(cnj=cnj, current_system=SourceSystem.FAKE)
    observed_at = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)
    movement = Movement(
        source=SourceSystem.FAKE,
        source_event_id="fixture-mov-001",
        event_at=observed_at,
        observed_at=observed_at,
        type_raw="Decisão proferida",
        type_normalized="decisao",
        description="Movimentação exclusivamente fictícia para teste.",
        document_ref="fixture://documento-001",
        correlation_id="demo-001",
    )
    connector = FakeConnector(
        movements=(movement,),
        documents={"fixture://documento-001": _example_pdf()},
    )
    with tempfile.TemporaryDirectory(prefix="legal-monitor-demo-") as temporary:
        root = Path(temporary)
        download = connector.fetch_document(
            process,
            "fixture://documento-001",
            root / "download.pdf",
        )
        record = DocumentService(root / "documents").store_pdf(
            download.target_path,
            process=process,
            movement_type=movement.type_normalized,
            observed_at=observed_at,
        )
        notifier = FakeNotifier()
        receipt = notifier.send(
            NotificationMessage(
                title="LCF Legal Monitor — demonstração segura",
                body=(
                    f"Movimentação fictícia detectada no processo {cnj.masked()}. "
                    "Nenhum dado real ou acesso externo foi utilizado."
                ),
                correlation_id="demo-001",
                demo_only=True,
            )
        )
        _emit(
            {
                "safe_demo": True,
                "network_used": False,
                "process": cnj.masked(),
                "movement_fingerprint": movement.fingerprint,
                "document_sha256": record.sha256,
                "page_count": record.page_count,
                "stored": record.storage_path.exists(),
                "notification": {
                    "accepted": receipt.accepted,
                    "channel": receipt.channel,
                    "provider_id": receipt.provider_id,
                },
                "production_storage_untouched": (
                    str(settings.storage_dir) not in str(record.storage_path)
                ),
            }
        )
    return 0


def notification_demo_discord() -> int:
    settings = Settings.from_env()
    if not settings.discord_demo_enabled:
        raise ConfigError(
            "Demonstração Discord desativada; configure DISCORD_DEMO_ENABLED=true depois "
            "de guardar um webhook novo no Keychain"
        )
    webhook_url = MacOSKeychainSecretProvider().get(
        service=settings.discord_webhook_keychain_service,
        account=settings.discord_webhook_keychain_account,
    )
    with tempfile.TemporaryDirectory(prefix="legal-monitor-discord-demo-") as temporary:
        notifier = DiscordWebhookNotifier(webhook_url, allowed_attachment_root=temporary)
        attachment_path = Path(temporary) / "prova_ficticia.pdf"
        attachment_path.write_bytes(_example_pdf())
        attachment_path.chmod(0o600)
        receipt = notifier.send(
            NotificationMessage(
                title="LCF Legal Monitor — prova técnica",
                body=(
                    "Processo: *******-**.2026.*.**.****\n"
                    "Origem: TJRJ / FONTE FICTÍCIA\n"
                    "Movimentação: decisão proferida (fixture)\n"
                    "Peça: prova_ficticia.pdf\n"
                    "Atenção: demonstração sem dado real; prazo não calculado."
                ),
                correlation_id="discord-demo-v2",
                demo_only=True,
                attachments=(
                    NotificationAttachment(
                        path=attachment_path,
                        filename="prova_ficticia.pdf",
                    ),
                ),
            )
        )
    _emit(
        {
            "ok": True,
            "demo_only": True,
            "real_process_data_used": False,
            "channel": receipt.channel,
            "provider_id": receipt.provider_id,
            "attachment": "prova_ficticia.pdf",
        }
    )
    return 0


def summary_demo() -> int:
    result = SummaryService(FakeSummaryProvider(), enabled=True).summarize(FAKE_EXTRACTED_DOCUMENT)
    _emit(
        {
            "safe_demo": True,
            "network_used": False,
            "real_process_data_used": False,
            "summary": result.as_output_json(),
        }
    )
    return 0


def secret_set(name: str) -> int:
    settings = Settings.from_env()
    accounts = {"smtp": settings.smtp_username}
    account = accounts.get(name)
    if not account:
        raise ConfigError(f"Segredo {name!r} desconhecido ou conta não configurada no .env")
    value = getpass.getpass(f"Cole o valor de {name!r} para {account} (não aparece na tela): ")
    KeyringSecretStore().set(name, account, value.strip())
    _emit({"ok": True, "secret": name, "account": account, "stored_in": "cofre do sistema"})
    return 0


def _email_notifier(settings: Settings, recipients: tuple[str, ...], root: Path) -> EmailNotifier:
    if not settings.email_enabled:
        raise ConfigError("E-mail desativado; configure EMAIL_ENABLED=true no .env")
    password = KeyringSecretStore().get("smtp", settings.smtp_username)
    return EmailNotifier(
        sender=settings.email_from,
        recipients=recipients,
        transport=SmtpSslTransport(
            settings.smtp_host, settings.smtp_port, settings.smtp_username, password
        ),
        allowed_attachment_root=root,
        maximum_attachment_bytes=settings.email_max_attachment_bytes,
    )


def email_test(group: str) -> int:
    settings = Settings.from_env()
    recipients = settings.email_operator_to if group == "operator" else settings.email_lawyer_to
    with tempfile.TemporaryDirectory(prefix="legal-monitor-email-test-") as temporary:
        root = Path(temporary)
        attachment_path = root / "prova_ficticia.pdf"
        attachment_path.write_bytes(_example_pdf())
        receipt = _email_notifier(settings, recipients, root).send(
            NotificationMessage(
                title="[LCF Monitor] Teste de envio",
                body=(
                    "Processo: *******-**.2026.*.**.****\n"
                    "Origem: TESTE (sem acesso a tribunal)\n"
                    "Movimentação: fictícia\n"
                    "Anexo: prova_ficticia.pdf (PDF em branco)\n\n"
                    "Se você recebeu este e-mail, o canal está funcionando."
                ),
                correlation_id="email-test",
                demo_only=True,
                attachments=(
                    NotificationAttachment(path=attachment_path, filename="prova_ficticia.pdf"),
                ),
            )
        )
    _emit(
        {
            "ok": True,
            "channel": receipt.channel,
            "recipients": len(recipients),
            "real_process_data_used": False,
        }
    )
    return 0


def sources_for(number: str) -> int:
    cnj = CnjNumber.parse(number)
    _emit(
        {
            "process": cnj.masked(),
            "sources": [
                {"key": item.key, "tribunal": item.tribunal, "url": item.base_url}
                for item in candidate_sources(cnj)
            ],
        }
    )
    return 0


def _session_manager(settings: Settings, *, headless: bool | None = None) -> BrowserSessionManager:
    return BrowserSessionManager(
        settings.browser_profile_dir,
        headless=settings.browser_headless if headless is None else headless,
        channel=settings.browser_channel,
        visible_for_blocked=settings.browser_visible_for_blocked,
    )


def _operator_notifier(settings: Settings) -> EmailNotifier | None:
    if settings.email_enabled and settings.email_operator_to:
        return _email_notifier(settings, settings.email_operator_to, settings.temp_dir)
    return None


def _auth_alert_service(settings: Settings) -> AuthAlertService:
    return AuthAlertService(
        PostgresManualActionStore(settings.database_url), _operator_notifier(settings)
    )


def auth_open(source: str, click_certificate: bool) -> int:
    settings = Settings.from_env()
    endpoint = get_endpoint(source)
    notifier = _operator_notifier(settings)
    print(
        f"Abrindo {endpoint.base_url} com o token USB. Escolha o certificado, digite o PIN se "
        "pedir e aprove o 2FA no celular. A janela fecha sozinha quando a sessão ficar válida.",
        file=sys.stderr,
    )

    def on_waiting() -> None:
        print("Aguardando aprovação do 2FA no celular...", file=sys.stderr)
        if notifier is None:
            return
        # Falha no aviso nunca pode derrubar o login que a pessoa está fazendo.
        try:
            notifier.send(build_approval_message(endpoint, f"approval-{endpoint.key}"))
        except EmailNotificationError as exc:
            print(f"Aviso por e-mail não enviado: {exc}", file=sys.stderr)

    manager = _session_manager(settings, headless=False)
    result = manager.login(
        endpoint,
        click_certificate=click_certificate,
        on_waiting_approval=on_waiting,
    )
    payload: dict[str, Any] = {"source": result.source, "session": result.state.value}
    if result.detail:
        payload["motivo"] = result.detail
    if manager.last_trace_path is not None:
        payload["login_trace"] = str(manager.last_trace_path)
    if result.state is SessionState.VALID:
        try:
            outcome = _auth_alert_service(settings).handle(
                endpoint, result.state, now=datetime.now(UTC)
            )
            payload["resolved_actions"] = outcome.resolved_actions
        except Exception as exc:
            payload["audit_warning"] = f"banco indisponível ({type(exc).__name__})"
    _emit(payload)
    return 0 if result.state is SessionState.VALID else 1


def auth_check(source: str | None, notify: bool) -> int:
    settings = Settings.from_env()
    endpoints = [get_endpoint(source)] if source else list(CATALOG.values())
    manager = _session_manager(settings)
    results = []
    all_valid = True
    for endpoint in endpoints:
        check = manager.check(endpoint)
        entry: dict[str, Any] = {"source": check.source, "session": check.state.value}
        if check.state is not SessionState.VALID:
            all_valid = False
        if notify:
            outcome = _auth_alert_service(settings).handle(
                endpoint, check.state, now=datetime.now(UTC)
            )
            entry.update({"action_opened": outcome.action_opened, "notified": outcome.notified})
        results.append(entry)
    _emit({"sessions": results})
    return 0 if all_valid else 1


def session_watch(source: str, every_minutes: int, max_hours: float, notify: bool) -> int:
    """Mede quanto tempo a sessão humana dura sob verificações periódicas."""
    settings = Settings.from_env()
    endpoint = get_endpoint(source)
    manager = _session_manager(settings)
    log_path = settings.temp_dir / f"session-watch-{source}.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    first_valid: datetime | None = None
    last_valid: datetime | None = None
    with log_path.open("a", encoding="utf-8") as log:
        while (datetime.now(UTC) - started).total_seconds() < max_hours * 3600:
            now = datetime.now(UTC)
            state = manager.check(endpoint).state
            log.write(f"{now.isoformat()},{source},{state.value}\n")
            log.flush()
            print(
                f"{now.astimezone().strftime('%H:%M:%S')} {source}: {state.value}", file=sys.stderr
            )
            if state is SessionState.VALID:
                first_valid = first_valid or now
                last_valid = now
            elif state in (SessionState.AUTH_REQUIRED, SessionState.CAPTCHA_REQUIRED):
                if notify:
                    with contextlib.suppress(Exception):
                        _auth_alert_service(settings).handle(endpoint, state, now=now)
                break
            time.sleep(every_minutes * 60)
    duration = (last_valid - first_valid).total_seconds() / 60 if first_valid and last_valid else 0
    _emit(
        {
            "source": source,
            "first_valid": first_valid.isoformat() if first_valid else None,
            "last_valid": last_valid.isoformat() if last_valid else None,
            "valid_for_at_least_minutes": round(duration, 1),
            "check_interval_minutes": every_minutes,
            "log": str(log_path),
        }
    )
    return 0


def import_processes(path: str, lawyer: str, actor: str, dry_run: bool) -> int:
    """Importa a carteira (um número por linha) e separa por site provável."""
    portfolio = parse_portfolio(Path(path).read_text(encoding="utf-8"))
    created = existing = rejected = 0
    service = None if dry_run else _admin_service()
    for entry in portfolio.entries:
        if service is None or entry.tribunal is None:
            continue
        try:
            record = service.register_process(
                cnj_value=str(entry.cnj),
                lawyer_reference=lawyer,
                sensitivity=entry.sensitivity,
                actor_id=actor,
            )
        except (AdminValidationError, AdminRepositoryError):
            rejected += 1
            continue
        if record.created:
            created += 1
        else:
            existing += 1
        if entry.site_override:
            forced = CATALOG[entry.site_override]
            PostgresMonitorRepository(Settings.from_env().database_url).record_source(
                record.id,
                system=forced.system.value,
                source_key=forced.key,
                at=datetime.now(UTC),
            )
    _emit(
        {
            "ok": True,
            "dry_run": dry_run,
            "valid": len(portfolio.entries),
            "created": created,
            "already_registered": existing,
            "rejected": rejected,
            "invalid_check_digits": portfolio.invalid,
            "not_cnj": portfolio.not_cnj,
            "duplicates": portfolio.duplicates,
            "by_likely_site": {
                site: {
                    "count": len(entries),
                    "restricted": sum(e.sensitivity is Sensitivity.RESTRICTED for e in entries),
                }
                for site, entries in portfolio.by_site().items()
            },
        }
    )
    return 0


def sites_report() -> int:
    """Carteira cadastrada por site: onde já foi encontrado ou onde será procurado."""
    settings = Settings.from_env()
    repository = PostgresMonitorRepository(settings.database_url)
    statuses = repository.statuses()
    lookups = repository.lookups()
    now = datetime.now(UTC)
    report: dict[str, dict[str, Any]] = {}
    for process in repository.active_processes():
        if process.source_key:
            site = process.source_key
        else:
            upcoming = next_candidate(process, lookups, now)
            site = f"a-descobrir:{upcoming}" if upcoming else "nao-encontrado-em-nenhum-site"
        bucket = report.setdefault(
            site, {"count": 0, "status": {}, "last_success": None, "procura": {}}
        )
        bucket["count"] += 1
        status, last_success = statuses.get(process.id, ("SEM_ESTADO", None))
        bucket["status"][status] = bucket["status"].get(status, 0) + 1
        for key in candidate_keys(process.cnj):
            result = lookups.get((process.id, key))
            if result is not None and result[0] != "FOUND":
                label = f"{result[0]}@{key}"
                bucket["procura"][label] = bucket["procura"].get(label, 0) + 1
        if last_success and (
            bucket["last_success"] is None or last_success > bucket["last_success"]
        ):
            bucket["last_success"] = last_success
    for bucket in report.values():
        if bucket["last_success"] is not None:
            bucket["last_success"] = bucket["last_success"].isoformat()
    _emit({"ok": True, "sites": dict(sorted(report.items(), key=lambda item: -item[1]["count"]))})
    return 0


def admin_reset_history(number: str, actor: str) -> int:
    settings = Settings.from_env()
    cnj = CnjNumber.parse(number)
    repository = PostgresMonitorRepository(settings.database_url)
    process_id = repository.process_id_for(cnj.digits)
    if process_id is None:
        _emit({"ok": False, "error": "Processo não cadastrado"})
        return 1
    removed = repository.reset_history(process_id, actor_id=actor, at=datetime.now(UTC))
    _emit({"ok": True, "process": cnj.masked(), "removed": removed})
    return 0


def structure_diagnostic(number: str, site: str) -> int:
    """Mapa da página do processo só com estrutura (ids/classes), para ajustar o leitor."""
    settings = Settings.from_env()
    cnj = CnjNumber.parse(number)
    endpoint = get_endpoint(site)
    connector = connector_for(endpoint)
    if connector is None:
        raise ConfigError(f"Site {site} ainda não tem robô")
    manager = _session_manager(settings)
    with manager.context(endpoint, headless=manager.headless_for(endpoint)) as context:
        page = connector.open_autos(context, cnj)
        stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
        path = settings.temp_dir / "diagnostico" / f"estrutura-autos-{site}-{stamp}.json"
        connector.dump_structure(page, path)
        pagination_ids = page.evaluate(
            '() => [...document.querySelectorAll(\'[id*="Pagin"], [id*="pagin"]\')]'
            ".map((e) => e.id).slice(0, 40)"
        )
    _emit(
        {
            "ok": True,
            "site": site,
            "process": cnj.masked(),
            "estrutura": str(path),
            "ids_de_paginacao": pagination_ids,
        }
    )
    return 0


TJRJ_PUBLIC_SEARCH_URL = "https://www.tjrj.jus.br/processos"
_CAPTCHA_ANY = (
    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], "
    ".g-recaptcha, .h-captcha, [class*='captcha' i], [id*='captcha' i], img[src*='captcha' i]"
)


def _masked(value: str | None, limit: int = 120) -> str:
    return re.sub(r"\d{3,}", "N", " ".join((value or "").split()))[:limit]


def tjrj_diagnostic(number: str, skip_portal: bool) -> int:
    """Testa as duas vias do TJRJ legado para UM processo e devolve só estrutura (ADR-008):
    A) consulta pública sem login; B) Portal de Serviços após login humano com certificado."""
    from playwright.sync_api import sync_playwright

    settings = Settings.from_env()
    cnj = CnjNumber.parse(number)
    formatted = str(cnj)  # NNNNNNN-DD.AAAA.J.TR.OOOO
    out_dir = settings.temp_dir / "diagnostico"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
    report: dict[str, Any] = {"process": cnj.masked()}
    channel = {"channel": settings.browser_channel} if settings.browser_channel else {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **channel)
        try:
            context = browser.new_context(locale="pt-BR")
            page = context.new_page()
            page.goto(TJRJ_PUBLIC_SEARCH_URL, wait_until="domcontentloaded")
            with contextlib.suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=20_000)
            page.fill("#parte1ProcCNJ", formatted[:20])
            page.fill("#parte2ProcCNJ", formatted[21:])
            # O botão visível é só um ícone (lupa); outro "Pesquisar" com texto fica oculto.
            try:
                page.locator("[id='form:commandButton3']").first.click(timeout=10_000)
            except Exception:
                page.press("#parte2ProcCNJ", "Enter")
            page.wait_for_timeout(8_000)
            result_page = context.pages[-1]
            with contextlib.suppress(Exception):
                result_page.wait_for_load_state("networkidle", timeout=25_000)
            result_page.wait_for_timeout(3_000)
            path = out_dir / f"estrutura-tjrj-publica-{stamp}.json"
            EprocConnector.dump_structure(result_page, path)
            final = urlparse(result_page.url)
            report["consulta_publica"] = {
                "abas_abertas": len(context.pages),
                "destino": f"{final.hostname}{final.path}#{_masked(final.fragment, 60)}",
                "titulo": _masked(result_page.title(), 60),
                "captcha_na_tela": result_page.locator(_CAPTCHA_ANY).count(),
                "tabelas": result_page.locator("table").count(),
                "linhas_de_tabela": result_page.locator("table tr").count(),
                "elementos_movimento": result_page.locator(
                    "[class*='moviment' i], [id*='moviment' i]"
                ).count(),
                "estrutura": str(path),
            }
        finally:
            browser.close()
        if not skip_portal:
            endpoint = get_endpoint("tjrj-portal")
            browser = playwright.chromium.launch(headless=False, **channel)
            try:
                context = browser.new_context(locale="pt-BR")
                page = context.new_page()
                page.goto(endpoint.base_url, wait_until="domcontentloaded")
                page.wait_for_selector(endpoint.certificate_login_selector or "img", timeout=20_000)
                page.locator(endpoint.certificate_login_selector or "img").first.click()
                print(
                    "Escolha o certificado e digite o PIN na janela do Portal (até 5 min)...",
                    file=sys.stderr,
                )
                for _ in range(300):
                    if "portalservicos" in page.url:
                        break
                    page.wait_for_timeout(1_000)
                with contextlib.suppress(Exception):
                    page.wait_for_load_state("networkidle", timeout=25_000)
                page.wait_for_timeout(3_000)
                landed = urlparse(page.url)
                menu = []
                for item in page.locator(
                    "a:visible, [role=menuitem]:visible, button:visible"
                ).all()[:120]:
                    label = _masked(item.inner_text(), 60)
                    route = item.get_attribute("href") or item.get_attribute("routerlink") or ""
                    if label:
                        menu.append([label, _masked(route, 70)])
                fields = [
                    [
                        element.get_attribute("type") or "",
                        element.get_attribute("id")
                        or element.get_attribute("formcontrolname")
                        or "",
                        _masked(
                            element.get_attribute("placeholder")
                            or element.get_attribute("aria-label"),
                            60,
                        ),
                    ]
                    for element in page.locator("input:visible").all()[:20]
                ]
                path = out_dir / f"estrutura-tjrj-portal-{stamp}.json"
                EprocConnector.dump_structure(page, path)
                report["portal"] = {
                    "logado": "portalservicos" in page.url,
                    "destino": f"{landed.hostname}{landed.path}#{_masked(landed.fragment, 60)}",
                    "titulo": _masked(page.title(), 60),
                    "menu": menu[:80],
                    "campos": fields,
                    "estrutura": str(path),
                }
            finally:
                if browser.is_connected():
                    browser.close()
    report_path = out_dir / f"diagnostico-tjrj-{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit({"ok": True, "relatorio": str(report_path), **report})
    return 0


def monitor_run(
    site: str | None = None, notify_initial: bool = False, interactive_login: bool = True
) -> int:
    """Rodada completa: login por fonte, leitura, dedupe, download e e-mail (ADR-009)."""
    settings = Settings.from_env()
    alerts = _auth_alert_service(settings)
    operator = _operator_notifier(settings)

    def on_auth_problem(endpoint: SourceEndpoint, state: SessionState) -> None:
        with contextlib.suppress(Exception):
            alerts.handle(endpoint, state, now=datetime.now(UTC))

    def on_waiting(endpoint: SourceEndpoint) -> None:
        if operator is not None:
            with contextlib.suppress(EmailNotificationError):
                operator.send(build_approval_message(endpoint, f"approval-{endpoint.key}"))

    service = MonitorService(
        repository=PostgresMonitorRepository(settings.database_url),
        sessions=_session_manager(settings),
        documents=DocumentService(settings.storage_dir, max_bytes=settings.max_document_bytes),
        lawyer_notifier=(
            _email_notifier(settings, settings.email_lawyer_to, settings.storage_dir)
            if settings.email_enabled and settings.email_lawyer_to
            else None
        ),
        on_auth_problem=on_auth_problem,
        on_waiting_approval=on_waiting,
        diagnostics_dir=settings.temp_dir / "diagnostico",
        max_attachment_bytes=settings.email_max_attachment_bytes,
        notify_initial=notify_initial,
        interactive_login=interactive_login,
    )
    summary = service.run(site=site)
    payload = {"ok": True, "site": site or "todos", **summary.as_dict()}
    # Registro de cada rodada (números mascarados, sem conteúdo) para conferência posterior,
    # inclusive quando o robô roda pelo agendador sem terminal aberto.
    log_dir = Path.cwd() / "logs"  # mesma raiz usada por Settings.from_env()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"monitor-{site or 'todos'}-{stamp}.json"
    log_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    payload["log"] = str(log_path)
    _emit(payload)
    return 0


def fetch_latest(number: str, send: bool, source: str | None) -> int:
    settings = Settings.from_env()
    cnj = CnjNumber.parse(number)
    notifier = (
        _email_notifier(settings, settings.email_lawyer_to, settings.storage_dir) if send else None
    )
    service = LatestMovementService(
        sessions=_session_manager(settings),
        documents=DocumentService(settings.storage_dir, max_bytes=settings.max_document_bytes),
        diagnostics_dir=settings.temp_dir / "diagnostico",
        notifier=notifier,
        max_attachment_bytes=settings.email_max_attachment_bytes,
    )
    result = service.run(cnj, source_key=source)
    _emit({"ok": result.found, **result.as_dict()})
    return 0 if result.found else 1


def _scheduler_components() -> tuple[Settings, PostgresSchedulerRepository, RetryPolicy]:
    settings = Settings.from_env()
    repository = PostgresSchedulerRepository(settings.database_url)
    policy = RetryPolicy(
        base_seconds=settings.scheduler_base_backoff_seconds,
        maximum_seconds=settings.scheduler_max_backoff_seconds,
    )
    return settings, repository, policy


def scheduler_heartbeat(worker_id: str) -> int:
    _, repository, _ = _scheduler_components()
    observed_at = datetime.now(UTC)
    try:
        repository.record_heartbeat(
            worker_id=worker_id,
            seen_at=observed_at,
            healthy=True,
            details={"source": "cli"},
        )
    except Exception as exc:
        _emit(
            {
                "heartbeat_recorded": False,
                "error_type": type(exc).__name__,
            }
        )
        return 1
    _emit(
        {
            "heartbeat_recorded": True,
            "worker_id": worker_id,
            "observed_at": observed_at.isoformat(),
        }
    )
    return 0


def scheduler_health() -> int:
    settings, repository, _ = _scheduler_components()
    try:
        health = repository.health(
            checked_at=datetime.now(UTC),
            worker_stale_seconds=settings.worker_stale_seconds,
        )
    except Exception as exc:
        _emit(
            {
                "database_accessible": False,
                "platform_alive": False,
                "error_type": type(exc).__name__,
            }
        )
        return 1
    _emit(health.as_dict())
    return 0 if health.platform_alive else 1


def scheduler_enqueue_healthcheck(idempotency_scope: str) -> int:
    settings, repository, _ = _scheduler_components()
    enqueued = repository.enqueue(
        job_type="SYSTEM_HEALTHCHECK",
        due_at=datetime.now(UTC),
        idempotency_scope=idempotency_scope,
        max_attempts=settings.scheduler_max_attempts,
    )
    _emit(
        {
            "job_id": str(enqueued.id),
            "correlation_id": str(enqueued.correlation_id),
            "created": enqueued.created,
        }
    )
    return 0


def scheduler_run_once(worker_id: str) -> int:
    settings, repository, policy = _scheduler_components()
    worker = SchedulerWorker(
        repository=repository,
        worker_id=worker_id,
        handlers={"SYSTEM_HEALTHCHECK": lambda lease: None},
        retry_policy=policy,
        lease_seconds=settings.scheduler_lease_seconds,
        batch_size=settings.scheduler_batch_size,
    )
    _emit(worker.run_once().as_dict())
    return 0


def _admin_service() -> AdminService:
    settings = Settings.from_env()
    return AdminService(
        PostgresAdminRepository(settings.database_url),
        scheduler_max_attempts=settings.scheduler_max_attempts,
    )


def admin_add_lawyer(code: str, name: str, actor: str) -> int:
    record = _admin_service().register_lawyer(
        reference_code=code,
        display_name=name,
        actor_id=actor,
    )
    _emit({"ok": True, "lawyer": record.as_dict()})
    return 0


def admin_add_process(number: str, lawyer: str, sensitivity: str, actor: str) -> int:
    record = _admin_service().register_process(
        cnj_value=number,
        lawyer_reference=lawyer,
        sensitivity=Sensitivity(sensitivity),
        actor_id=actor,
    )
    _emit({"ok": True, "process": record.as_dict()})
    return 0


def admin_list_processes(include_inactive: bool) -> int:
    records = _admin_service().list_processes(include_inactive=include_inactive)
    _emit(
        {
            "ok": True,
            "count": len(records),
            "processes": [record.as_dict() for record in records],
        }
    )
    return 0


def admin_deactivate_process(number: str, actor: str) -> int:
    result = _admin_service().deactivate_process(
        cnj_value=number,
        actor_id=actor,
    )
    _emit({"ok": True, "result": result.as_dict()})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="legal-monitor")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help="verifica configuração e dependências locais")
    cnj_parser = subcommands.add_parser("validate-cnj", help="valida um número CNJ")
    cnj_parser.add_argument("number")
    subcommands.add_parser("demo", help="executa fatia vertical fictícia sem rede")
    subcommands.add_parser(
        "notification-demo-discord",
        help="envia uma fixture fixa, sem dado processual, a um webhook Discord privado",
    )
    subcommands.add_parser(
        "summary-demo",
        help="gera resumo factual rastreável de uma fixture fixa, sem rede ou dado real",
    )
    heartbeat_parser = subcommands.add_parser(
        "scheduler-heartbeat", help="registra o sinal interno do worker no PostgreSQL"
    )
    heartbeat_parser.add_argument("--worker-id", default="local-worker")
    subcommands.add_parser(
        "scheduler-health", help="mostra saúde da agenda sem confundir heartbeat e processos"
    )
    enqueue_parser = subcommands.add_parser(
        "scheduler-enqueue-healthcheck",
        help="agenda um job fictício e idempotente para teste local",
    )
    enqueue_parser.add_argument("--key", required=True)
    worker_parser = subcommands.add_parser(
        "scheduler-run-once", help="executa um lote vencido e encerra"
    )
    worker_parser.add_argument("--worker-id", default="local-worker")
    lawyer_parser = subcommands.add_parser(
        "admin-add-lawyer", help="cadastra um responsável local com trilha de auditoria"
    )
    lawyer_parser.add_argument("--code", required=True)
    lawyer_parser.add_argument("--name", required=True)
    lawyer_parser.add_argument("--actor", default="local-admin")
    process_parser = subcommands.add_parser(
        "admin-add-process", help="cadastra processo TJRJ e agenda a primeira verificação"
    )
    process_parser.add_argument("number")
    process_parser.add_argument("--lawyer", required=True)
    process_parser.add_argument(
        "--sensitivity",
        choices=[value.value for value in Sensitivity],
        default=Sensitivity.CONFIDENTIAL.value,
    )
    process_parser.add_argument("--actor", default="local-admin")
    list_parser = subcommands.add_parser(
        "admin-list-processes", help="lista processos com número mascarado e estado explícito"
    )
    list_parser.add_argument("--include-inactive", action="store_true")
    deactivate_parser = subcommands.add_parser(
        "admin-deactivate-process", help="desativa processo, agenda e estado sem apagar histórico"
    )
    deactivate_parser.add_argument("number")
    deactivate_parser.add_argument("--actor", default="local-admin")
    secret_parser = subcommands.add_parser(
        "secret-set", help="grava um segredo no cofre do sistema, digitado sem eco"
    )
    secret_parser.add_argument("name", choices=["smtp"])
    email_parser = subcommands.add_parser(
        "email-test", help="envia e-mail fictício com PDF em branco para validar o canal"
    )
    email_parser.add_argument("--to", choices=["operator", "lawyer"], default="operator")
    sources_parser = subcommands.add_parser(
        "sources-for", help="mostra as fontes candidatas de um número CNJ, sem rede"
    )
    sources_parser.add_argument("number")
    auth_open_parser = subcommands.add_parser(
        "auth-open", help="abre janela visível para login humano com 2FA e salva a sessão"
    )
    auth_open_parser.add_argument("source", choices=sorted(CATALOG))
    auth_open_parser.add_argument(
        "--no-certificate",
        action="store_true",
        help="não clica em 'Certificado Digital'; a pessoa escolhe o método na tela",
    )
    auth_check_parser = subcommands.add_parser(
        "auth-check", help="verifica sessões salvas; --notify avisa o operador se expiraram"
    )
    auth_check_parser.add_argument("source", nargs="?", choices=sorted(CATALOG))
    auth_check_parser.add_argument("--notify", action="store_true")
    watch_parser = subcommands.add_parser(
        "session-watch", help="mede a duração real da sessão com verificações periódicas"
    )
    watch_parser.add_argument("source", choices=sorted(CATALOG))
    watch_parser.add_argument("--every", type=int, default=5, help="minutos entre verificações")
    watch_parser.add_argument("--max-hours", type=float, default=12.0)
    watch_parser.add_argument("--notify", action="store_true")
    monitor_parser = subcommands.add_parser(
        "monitor-run", help="rodada completa: login, leitura, novidades, download e e-mail"
    )
    monitor_parser.add_argument(
        "--site", choices=sorted(CATALOG), help="roda só o robô deste site (agenda própria)"
    )
    monitor_parser.add_argument(
        "--notify-initial",
        action="store_true",
        help="1ª rodada: um e-mail por processo (padrão: um resumo único)",
    )
    monitor_parser.add_argument(
        "--no-interactive-login",
        action="store_true",
        help="não abre janela de login: sessão caída só gera aviso (robôs de hora em hora)",
    )
    import_parser = subcommands.add_parser(
        "import-processes", help="importa a carteira (um número por linha) e separa por site"
    )
    import_parser.add_argument("path")
    import_parser.add_argument("--lawyer", required=True)
    import_parser.add_argument("--actor", default="local-admin")
    import_parser.add_argument("--dry-run", action="store_true")
    subcommands.add_parser("sites-report", help="carteira cadastrada por site e estado")
    reset_parser = subcommands.add_parser(
        "admin-reset-history",
        help="apaga o histórico gravado pelo robô para um processo (refaz a linha de base)",
    )
    reset_parser.add_argument("number")
    reset_parser.add_argument("--actor", default="local-admin")
    diagnostic_parser = subcommands.add_parser(
        "diagnostico-estrutura",
        help="gera o mapa da página do processo só com estrutura (sem conteúdo)",
    )
    diagnostic_parser.add_argument("number")
    diagnostic_parser.add_argument("--site", required=True, choices=sorted(CATALOG))
    tjrj_parser = subcommands.add_parser(
        "diagnostico-tjrj",
        help="testa consulta pública e Portal de Serviços do TJRJ para UM processo (só estrutura)",
    )
    tjrj_parser.add_argument("number")
    tjrj_parser.add_argument("--sem-portal", action="store_true", help="só a consulta pública")
    latest_parser = subcommands.add_parser(
        "fetch-latest",
        help="busca a última movimentação, baixa o documento e (--send) envia ao advogado",
    )
    latest_parser.add_argument("number")
    latest_parser.add_argument("--send", action="store_true")
    latest_parser.add_argument("--source", choices=sorted(CATALOG))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor()
        if args.command == "validate-cnj":
            return validate_cnj(args.number)
        if args.command == "demo":
            return demo()
        if args.command == "notification-demo-discord":
            return notification_demo_discord()
        if args.command == "summary-demo":
            return summary_demo()
        if args.command == "scheduler-heartbeat":
            return scheduler_heartbeat(args.worker_id)
        if args.command == "scheduler-health":
            return scheduler_health()
        if args.command == "scheduler-enqueue-healthcheck":
            return scheduler_enqueue_healthcheck(args.key)
        if args.command == "scheduler-run-once":
            return scheduler_run_once(args.worker_id)
        if args.command == "admin-add-lawyer":
            return admin_add_lawyer(args.code, args.name, args.actor)
        if args.command == "admin-add-process":
            return admin_add_process(args.number, args.lawyer, args.sensitivity, args.actor)
        if args.command == "admin-list-processes":
            return admin_list_processes(args.include_inactive)
        if args.command == "admin-deactivate-process":
            return admin_deactivate_process(args.number, args.actor)
        if args.command == "secret-set":
            return secret_set(args.name)
        if args.command == "email-test":
            return email_test(args.to)
        if args.command == "sources-for":
            return sources_for(args.number)
        if args.command == "auth-open":
            return auth_open(args.source, not args.no_certificate)
        if args.command == "auth-check":
            return auth_check(args.source, args.notify)
        if args.command == "session-watch":
            return session_watch(args.source, args.every, args.max_hours, args.notify)
        if args.command == "monitor-run":
            return monitor_run(args.site, args.notify_initial, not args.no_interactive_login)
        if args.command == "import-processes":
            return import_processes(args.path, args.lawyer, args.actor, args.dry_run)
        if args.command == "sites-report":
            return sites_report()
        if args.command == "admin-reset-history":
            return admin_reset_history(args.number, args.actor)
        if args.command == "diagnostico-estrutura":
            return structure_diagnostic(args.number, args.site)
        if args.command == "diagnostico-tjrj":
            return tjrj_diagnostic(args.number, args.sem_portal)
        if args.command == "fetch-latest":
            return fetch_latest(args.number, args.send, args.source)
    except (
        AdminRepositoryError,
        AdminValidationError,
        BrowserUnavailableError,
        ConfigError,
        ConnectorError,
        DocumentValidationError,
        DiscordNotificationError,
        EmailNotificationError,
        InvalidCnjNumber,
        KeychainSecretError,
        SecretStoreError,
        UnknownSourceError,
    ) as exc:
        _emit({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
