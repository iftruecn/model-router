"""
Internationalization (i18n) module for Model Router.

Provides translations for all user-facing strings in 7 languages:
- EN: English
- ZH: Chinese (Simplified)
- JA: Japanese
- KO: Korean
- ES: Spanish
- FR: French
- DE: German

Usage:
    from model_router.locales.i18n import t, set_language, get_language

    # Set language (auto-detect from environment or explicit)
    set_language("zh")

    # Get translated string
    print(t("setup.welcome"))
    print(t("error.model_not_found", model_id="dall-e-3"))
"""

import os
import locale
from typing import Optional

# Current language (can be set via set_language() or env var MODEL_ROUTER_LANG)
_current_language: str = "en"

# Supported languages
SUPPORTED_LANGUAGES = ("en", "zh", "ja", "ko", "es", "fr", "de")

# Language names (for display in CLI)
LANGUAGE_NAMES = {
    "en": "English",
    "zh": "中文",
    "ja": "日本語",
    "ko": "한국어",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
}

# ============================================================
# Translation strings
# ============================================================

TRANSLATIONS = {
    # ----------------------------------------------------------
    # CLI Setup Wizard
    # ----------------------------------------------------------
    "setup.welcome": {
        "en": "Model Router — Interactive Setup Wizard",
        "zh": "Model Router — 交互式配置向导",
        "ja": "Model Router — インタラクティブ設定ウィザード",
        "ko": "Model Router — 대화형 설정 마법사",
        "es": "Model Router — Asistente de configuración interactivo",
        "fr": "Model Router — Assistant de configuration interactif",
        "de": "Model Router — Interaktiver Einrichtungsassistent",
    },
    "setup.description": {
        "en": "Configure which models can be auto-selected by the router",
        "zh": "配置哪些模型可以被路由自动选择",
        "ja": "ルーターが自動的に選択できるモデルを設定します",
        "ko": "라우터가 자동으로 선택할 수 있는 모델을 구성합니다",
        "es": "Configure qué modelos pueden ser seleccionados automáticamente",
        "fr": "Configurez quels modèles peuvent être sélectionnés automatiquement",
        "de": "Konfigurieren Sie, welche Modelle automatisch ausgewählt werden können",
    },
    "setup.config_path": {
        "en": "Config file path",
        "zh": "配置文件路径",
        "ja": "設定ファイルパス",
        "ko": "설정 파일 경로",
        "es": "Ruta del archivo de configuración",
        "fr": "Chemin du fichier de configuration",
        "de": "Konfigurationsdateipfad",
    },
    "setup.no_models": {
        "en": "No models found in config. Add models first, then run setup again.",
        "zh": "配置中未找到模型。请先添加模型，然后重新运行配置。",
        "ja": "設定にモデルが見つかりません。先にモデルを追加してください。",
        "ko": "설정에서 모델을 찾을 수 없습니다. 먼저 모델을 추가하세요.",
        "es": "No se encontraron modelos en la configuración. Agregue modelos primero.",
        "fr": "Aucun modèle trouvé dans la configuration. Ajoutez des modèles d'abord.",
        "de": "Keine Modelle in der Konfiguration gefunden. Fügen Sie zuerst Modelle hinzu.",
    },
    "setup.select_manual": {
        "en": "Which models should be MANUAL-ONLY?",
        "zh": "哪些模型应该设为「仅手动选择」？",
        "ja": "どのモデルを「手動選択のみ」に設定しますか？",
        "ko": "어떤 모델을 '수동 선택만'으로 설정하시겠습니까?",
        "es": "¿Qué modelos deben ser SOLO MANUALES?",
        "fr": "Quels modèles doivent être MANUELS UNIQUEMENT ?",
        "de": "Welche Modelle sollen NUR MANUELL ausgewählt werden?",
    },
    "setup.current_mode": {
        "en": "current",
        "zh": "当前",
        "ja": "現在",
        "ko": "현재",
        "es": "actual",
        "fr": "actuel",
        "de": "aktuell",
    },
    "setup.select_hint": {
        "en": "Select numbers (e.g., 1,3,5 or 'all' or 'none')",
        "zh": "输入编号（如 1,3,5 或 'all' 全选 或 'none' 全不选）",
        "ja": "番号を入力（例：1,3,5 または 'all' / 'none'）",
        "ko": "번호 입력 (예: 1,3,5 또는 'all' 또는 'none')",
        "es": "Seleccione números (ej., 1,3,5 o 'all' o 'none')",
        "fr": "Sélectionnez les numéros (ex: 1,3,5 ou 'all' ou 'none')",
        "de": "Nummern auswählen (z.B. 1,3,5 oder 'all' oder 'none')",
    },
    "setup.selected_manual": {
        "en": "Selected {count} model(s) as manual-only",
        "zh": "已选择 {count} 个模型为「仅手动选择」",
        "ja": "{count} 個のモデルを手動選択のみに設定",
        "ko": "{count}개 모델을 수동 선택만으로 설정",
        "es": "{count} modelo(s) seleccionado(s) como solo manual",
        "fr": "{count} modèle(s) sélectionné(s) comme manuel uniquement",
        "de": "{count} Modell(e) als nur manuell ausgewählt",
    },
    "setup.expensive_detected": {
        "en": "Auto-detected expensive models",
        "zh": "自动检测到高成本模型",
        "ja": "高コストモデルを自動検出",
        "ko": "고비용 모델 자동 감지",
        "es": "Modelos costosos detectados automáticamente",
        "fr": "Modèles coûteux détectés automatiquement",
        "de": "Teure Modelle automatisch erkannt",
    },
    "setup.mark_expensive": {
        "en": "Mark these as manual-only too?",
        "zh": "是否也将这些设为「仅手动选择」？",
        "ja": "これらも「手動選択のみ」に設定しますか？",
        "ko": "이것도 '수동 선택만'으로 설정하시겠습니까?",
        "es": "¿Marcar estos como solo manuales también?",
        "fr": "Marquer ceux-ci comme manuels uniquement aussi ?",
        "de": "Diese auch als nur manuell markieren?",
    },
    "setup.preview": {
        "en": "Preview",
        "zh": "预览",
        "ja": "プレビュー",
        "ko": "미리보기",
        "es": "Vista previa",
        "fr": "Aperçu",
        "de": "Vorschau",
    },
    "setup.confirm_save": {
        "en": "Save this configuration?",
        "zh": "是否保存此配置？",
        "ja": "この設定を保存しますか？",
        "ko": "이 설정을 저장하시겠습니까?",
        "es": "¿Guardar esta configuración?",
        "fr": "Enregistrer cette configuration ?",
        "de": "Diese Konfiguration speichern?",
    },
    "setup.saved": {
        "en": "Config saved to: {path}",
        "zh": "配置已保存至：{path}",
        "ja": "設定を保存しました：{path}",
        "ko": "구성이 저장되었습니다: {path}",
        "es": "Configuración guardada en: {path}",
        "fr": "Configuration enregistrée dans : {path}",
        "de": "Konfiguration gespeichert unter: {path}",
    },
    "setup.complete": {
        "en": "Setup complete!",
        "zh": "配置完成！",
        "ja": "設定完了！",
        "ko": "설정 완료!",
        "es": "¡Configuración completa!",
        "fr": "Configuration terminée !",
        "de": "Einrichtung abgeschlossen!",
    },
    "setup.cancelled": {
        "en": "Cancelled. No changes saved.",
        "zh": "已取消，未保存任何更改。",
        "ja": "キャンセルされました。変更は保存されていません。",
        "ko": "취소되었습니다. 변경사항이 저장되지 않았습니다.",
        "es": "Cancelado. No se guardaron cambios.",
        "fr": "Annulé. Aucun changement enregistré.",
        "de": "Abgebrochen. Keine Änderungen gespeichert.",
    },
    "setup.start_hint": {
        "en": "Start the router:  model-router serve",
        "zh": "启动路由：model-router serve",
        "ja": "ルーターを起動：model-router serve",
        "ko": "라우터 시작: model-router serve",
        "es": "Iniciar el enrutador: model-router serve",
        "fr": "Démarrer le routeur : model-router serve",
        "de": "Router starten: model-router serve",
    },
    "setup.quick_complete": {
        "en": "Quick setup complete!",
        "zh": "快速配置完成！",
        "ja": "クイック設定完了！",
        "ko": "빠른 설정 완료!",
        "es": "¡Configuración rápida completa!",
        "fr": "Configuration rapide terminée !",
        "de": "Schnelleinrichtung abgeschlossen!",
    },
    "setup.current_config": {
        "en": "Current Model Configuration",
        "zh": "当前模型配置",
        "ja": "現在のモデル設定",
        "ko": "현재 모델 구성",
        "es": "Configuración actual del modelo",
        "fr": "Configuration actuelle du modèle",
        "de": "Aktuelle Modellkonfiguration",
    },
    "setup.no_config": {
        "en": "No models configured.",
        "zh": "未配置任何模型。",
        "ja": "モデルが設定されていません。",
        "ko": "구성된 모델이 없습니다.",
        "es": "No hay modelos configurados.",
        "fr": "Aucun modèle configuré.",
        "de": "Keine Modelle konfiguriert.",
    },

    # ----------------------------------------------------------
    # CLI Help
    # ----------------------------------------------------------
    "help.commands": {
        "en": "Commands",
        "zh": "命令",
        "ja": "コマンド",
        "ko": "명령",
        "es": "Comandos",
        "fr": "Commandes",
        "de": "Befehle",
    },
    "help.serve_desc": {
        "en": "Start the server (default)",
        "zh": "启动服务器（默认）",
        "ja": "サーバーを起動（デフォルト）",
        "ko": "서버 시작 (기본값)",
        "es": "Iniciar el servidor (predeterminado)",
        "fr": "Démarrer le serveur (par défaut)",
        "de": "Server starten (Standard)",
    },
    "help.setup_desc": {
        "en": "Interactive model configuration wizard",
        "zh": "交互式模型配置向导",
        "ja": "インタラクティブモデル設定ウィザード",
        "ko": "대화형 모델 설정 마법사",
        "es": "Asistente de configuración de modelos interactivo",
        "fr": "Assistant de configuration de modèle interactif",
        "de": "Interaktiver Modellkonfigurationsassistent",
    },
    "help.options": {
        "en": "Setup options",
        "zh": "配置选项",
        "ja": "設定オプション",
        "ko": "설정 옵션",
        "es": "Opciones de configuración",
        "fr": "Options de configuration",
        "de": "Einrichtungsoptionen",
    },
    "help.quick_desc": {
        "en": "Auto-detect expensive models",
        "zh": "自动检测高成本模型",
        "ja": "高コストモデルを自動検出",
        "ko": "고비용 모델 자동 감지",
        "es": "Detectar automáticamente modelos costosos",
        "fr": "Détecter automatiquement les modèles coûteux",
        "de": "Teure Modelle automatisch erkennen",
    },
    "help.list_desc": {
        "en": "Show current configuration",
        "zh": "显示当前配置",
        "ja": "現在の設定を表示",
        "ko": "현재 구성 표시",
        "es": "Mostrar configuración actual",
        "fr": "Afficher la configuration actuelle",
        "de": "Aktuelle Konfiguration anzeigen",
    },
    "help.config_desc": {
        "en": "Use custom config path",
        "zh": "使用自定义配置路径",
        "ja": "カスタム設定パスを使用",
        "ko": "사용자 정의 구성 경로 사용",
        "es": "Usar ruta de configuración personalizada",
        "fr": "Utiliser un chemin de configuration personnalisé",
        "de": "Benutzerdefinierten Konfigurationspfad verwenden",
    },

    # ----------------------------------------------------------
    # API / Error Messages
    # ----------------------------------------------------------
    "error.model_not_found": {
        "en": "Model '{model_id}' not found. Available: {available}",
        "zh": "模型 '{model_id}' 未找到。可用模型：{available}",
        "ja": "モデル '{model_id}' が見つかりません。利用可能：{available}",
        "ko": "모델 '{model_id}'을(를) 찾을 수 없습니다. 사용 가능: {available}",
        "es": "Modelo '{model_id}' no encontrado. Disponibles: {available}",
        "fr": "Modèle '{model_id}' introuvable. Disponibles : {available}",
        "de": "Modell '{model_id}' nicht gefunden. Verfügbar: {available}",
    },
    "error.invalid_mode": {
        "en": "Invalid mode '{mode}' (must be 'auto' or 'manual')",
        "zh": "无效模式 '{mode}'（必须是 'auto' 或 'manual'）",
        "ja": "無効なモード '{mode}'（'auto' または 'manual' を指定）",
        "ko": "잘못된 모드 '{mode}' ('auto' 또는 'manual'만 가능)",
        "es": "Modo inválido '{mode}' (debe ser 'auto' o 'manual')",
        "fr": "Mode invalide '{mode}' (doit être 'auto' ou 'manual')",
        "de": "Ungültiger Modus '{mode}' (muss 'auto' oder 'manual' sein)",
    },
    "api.mode_changed": {
        "en": "Model '{model_id}' is now {mode_desc}",
        "zh": "模型 '{model_id}' 现已设为{mode_desc}",
        "ja": "モデル '{model_id}' は{mode_desc}に変更されました",
        "ko": "모델 '{model_id}'이(가) {mode_desc}(으)로 변경되었습니다",
        "es": "El modelo '{model_id}' ahora está {mode_desc}",
        "fr": "Le modèle '{model_id}' est maintenant {mode_desc}",
        "de": "Modell '{model_id}' ist jetzt {mode_desc}",
    },
    "api.excluded_from_auto": {
        "en": "excluded from auto-routing",
        "zh": "排除在自动路由之外",
        "ja": "自動ルーティングから除外",
        "ko": "자동 라우팅에서 제외",
        "es": "excluido del enrutamiento automático",
        "fr": "exclu du routage automatique",
        "de": "vom automatischen Routing ausgeschlossen",
    },
    "api.included_in_auto": {
        "en": "included in auto-routing",
        "zh": "加入自动路由",
        "ja": "自動ルーティングに含まれる",
        "ko": "자동 라우팅에 포함",
        "es": "incluido en el enrutamiento automático",
        "fr": "inclus dans le routage automatique",
        "de": "im automatischen Routing enthalten",
    },

    # ----------------------------------------------------------
    # Common
    # ----------------------------------------------------------
    "common.yes": {
        "en": "yes",
        "zh": "是",
        "ja": "はい",
        "ko": "예",
        "es": "sí",
        "fr": "oui",
        "de": "ja",
    },
    "common.no": {
        "en": "no",
        "zh": "否",
        "ja": "いいえ",
        "ko": "아니오",
        "es": "no",
        "fr": "non",
        "de": "nein",
    },
    "common.auto": {
        "en": "auto",
        "zh": "自动",
        "ja": "自動",
        "ko": "자동",
        "es": "auto",
        "fr": "auto",
        "de": "auto",
    },
    "common.manual": {
        "en": "manual",
        "zh": "手动",
        "ja": "手動",
        "ko": "수동",
        "es": "manual",
        "fr": "manuel",
        "de": "manuell",
    },
}


def set_language(lang: str) -> None:
    """
    Set the current language.

    Args:
        lang: Language code (en, zh, ja, ko, es, fr, de)
    """
    global _current_language
    if lang.lower() in SUPPORTED_LANGUAGES:
        _current_language = lang.lower()
    else:
        _current_language = "en"


def get_language() -> str:
    """Get the current language code."""
    return _current_language


def detect_language() -> str:
    """
    Auto-detect language from environment.

    Checks MODEL_ROUTER_LANG env var first, then system locale.
    """
    # 1. Environment variable
    env_lang = os.environ.get("MODEL_ROUTER_LANG", "").lower()
    if env_lang in SUPPORTED_LANGUAGES:
        return env_lang

    # 2. System locale
    try:
        sys_locale = locale.getdefaultlocale()[0] or ""
        lang_code = sys_locale.split("_")[0].lower()
        if lang_code in SUPPORTED_LANGUAGES:
            return lang_code
    except Exception:
        pass

    return "en"


def t(key: str, **kwargs) -> str:
    """
    Get translated string by key.

    Args:
        key: Translation key (e.g., "setup.welcome")
        **kwargs: Format arguments (e.g., model_id="dall-e-3")

    Returns:
        Translated string, or English fallback if key not found.
    """
    translations = TRANSLATIONS.get(key, {})
    text = translations.get(_current_language, translations.get("en", key))

    # Format with kwargs if provided
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass

    return text


def init_language(explicit: Optional[str] = None) -> None:
    """
    Initialize language from explicit setting or auto-detect.

    Call this at application startup.
    """
    if explicit:
        set_language(explicit)
    else:
        set_language(detect_language())
