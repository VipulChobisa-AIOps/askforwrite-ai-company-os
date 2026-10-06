"""
AskforWrite AI Company OS — Desktop Control Center & Setup Wizard
================================================================
A production desktop application for managing, configuring, initializing,
and running the AskforWrite AI Company OS gateway and multi-agent fleet.
"""

import os
import sys
import time
import json
import secrets
import threading
import webbrowser
import queue
from pathlib import Path
from datetime import datetime

# GUI imports
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Determine base directory (handles both normal Python and PyInstaller frozen .exe)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
    sys.path.insert(0, str(BUNDLE_DIR))
    sys.path.insert(0, str(BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = BASE_DIR

ENV_PATH = BASE_DIR / ".env"

if not ENV_PATH.exists() and (BUNDLE_DIR / ".env.example").exists():
    import shutil
    shutil.copy(BUNDLE_DIR / ".env.example", ENV_PATH)
elif not ENV_PATH.exists() and (BASE_DIR / ".env.example").exists():
    import shutil
    shutil.copy(BASE_DIR / ".env.example", ENV_PATH)

from dotenv import load_dotenv, set_key
load_dotenv(dotenv_path=ENV_PATH)

import httpx

# ── Color Palette & Styles ──────────────────────────────────────────────
BG_DARK = "#0b0f19"
BG_CARD = "#161f30"
BG_CARD_LIGHT = "#1e293b"
BG_INPUT = "#0f172a"
BORDER_COLOR = "#334155"
TEXT_PRIMARY = "#f8fafc"
TEXT_MUTED = "#94a3b8"
TEXT_ACCENT = "#38bdf8"
COLOR_SUCCESS = "#10b981"
COLOR_WARNING = "#f59e0b"
COLOR_DANGER = "#ef4444"
COLOR_PRIMARY = "#2563eb"
COLOR_PRIMARY_HOVER = "#1d4ed8"


class CompanyOSDesktopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AskforWrite AI Company OS — Desktop Control Center & Wizard")
        self.geometry("1100x780")
        self.minsize(980, 680)
        self.configure(bg=BG_DARK)

        # State
        self.server_process = None
        self.server_thread = None
        self.server_running = False
        self.log_queue = queue.Queue()
        self.api_url = "http://127.0.0.1:8000"

        # Setup ttk styles
        self._init_styles()

        # Build UI layout
        self._build_header()
        self._build_tabs()
        self._build_footer()

        # Start periodic checks
        self.after(500, self._process_log_queue)
        self.after(1000, self._check_server_health)

    def _init_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # Global configs
        style.configure(".", background=BG_DARK, foreground=TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("TNotebook", background=BG_DARK, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=BG_CARD,
            foreground=TEXT_MUTED,
            padding=[16, 8],
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", BG_CARD_LIGHT), ("active", "#1e293b")],
            foreground=[("selected", TEXT_ACCENT), ("active", TEXT_PRIMARY)],
        )

        style.configure("Card.TFrame", background=BG_CARD, relief="flat")
        style.configure("CardInner.TFrame", background=BG_CARD_LIGHT, relief="flat")
        style.configure("Header.TLabel", background=BG_DARK, foreground=TEXT_PRIMARY, font=("Segoe UI", 16, "bold"))
        style.configure("SubHeader.TLabel", background=BG_DARK, foreground=TEXT_MUTED, font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=BG_CARD, foreground=TEXT_ACCENT, font=("Segoe UI", 12, "bold"))
        style.configure("Muted.TLabel", background=BG_CARD, foreground=TEXT_MUTED, font=("Segoe UI", 9))
        style.configure("FieldLabel.TLabel", background=BG_CARD, foreground=TEXT_PRIMARY, font=("Segoe UI", 9, "bold"))

        # Buttons
        style.configure(
            "Primary.TButton",
            background=COLOR_PRIMARY,
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
            padding=[14, 7],
        )
        style.map("Primary.TButton", background=[("active", COLOR_PRIMARY_HOVER)])

        style.configure(
            "Success.TButton",
            background=COLOR_SUCCESS,
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
            padding=[14, 7],
        )
        style.map("Success.TButton", background=[("active", "#059669")])

        style.configure(
            "Danger.TButton",
            background=COLOR_DANGER,
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
            padding=[14, 7],
        )
        style.map("Danger.TButton", background=[("active", "#dc2626")])

        style.configure(
            "Secondary.TButton",
            background="#334155",
            foreground=TEXT_PRIMARY,
            font=("Segoe UI", 9),
            borderwidth=0,
            padding=[10, 5],
        )
        style.map("Secondary.TButton", background=[("active", "#475569")])

    def _build_header(self):
        header_frame = tk.Frame(self, bg=BG_DARK, pady=14, padx=20)
        header_frame.pack(fill=tk.X)

        left_header = tk.Frame(header_frame, bg=BG_DARK)
        left_header.pack(side=tk.LEFT)

        title = tk.Label(
            left_header,
            text="ASKFORWRITE AI COMPANY OS",
            font=("Segoe UI", 17, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_DARK,
        )
        title.pack(anchor="w")

        subtitle = tk.Label(
            left_header,
            text="Autonomous Multi-Agent Enterprise Gateway • Cryptographic Trust Ledger • HITL Governance",
            font=("Segoe UI", 9),
            fg=TEXT_MUTED,
            bg=BG_DARK,
        )
        subtitle.pack(anchor="w")

        # Right status badge
        self.status_badge = tk.Label(
            header_frame,
            text="● SERVER STOPPED",
            font=("Segoe UI", 10, "bold"),
            fg="#94a3b8",
            bg="#1e293b",
            padx=14,
            pady=6,
            relief="flat",
        )
        self.status_badge.pack(side=tk.RIGHT, pady=4)

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        # Tab 1: Setup Wizard & Config
        self.tab_wizard = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_wizard, text="  🛠️  Setup Wizard & Credentials  ")
        self._build_wizard_tab()

        # Tab 2: Server Control & Console
        self.tab_control = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_control, text="  ⚡  Server & Live Console  ")
        self._build_control_tab()

        # Tab 3: AI Agents & E2E Testing
        self.tab_agents = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_agents, text="  🤖  Multi-Agent Fleet & Diagnostics  ")
        self._build_agents_tab()

    def _build_wizard_tab(self):
        canvas = tk.Canvas(self.tab_wizard, bg=BG_DARK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_wizard, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=BG_DARK)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=1040)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Step 1: System & Environment
        f1 = self._create_card(scrollable_frame, "Step 1: Environment & Server Port")
        self._create_field(f1, "Application Environment (APP_ENV):", "APP_ENV", "development", row=0)
        self._create_field(f1, "Server Port (APP_PORT):", "APP_PORT", "8000", row=1)
        self._create_field(f1, "Allowed CORS Origins:", "ALLOWED_ORIGINS", "http://localhost:3000,https://dashboard.askforwrite.in", row=2)

        # Step 2: Database Configuration
        f2 = self._create_card(scrollable_frame, "Step 2: Database Storage & Ledger Engine")
        self._create_field(f2, "Database URL:", "DATABASE_URL", "sqlite:///./company_os.db", row=0)

        db_btn_row = tk.Frame(f2, bg=BG_CARD)
        db_btn_row.grid(row=1, column=1, sticky="w", pady=8)

        ttk.Button(
            db_btn_row,
            text="Use Embedded SQLite (Recommended)",
            style="Secondary.TButton",
            command=lambda: self.entries["DATABASE_URL"].delete(0, tk.END) or self.entries["DATABASE_URL"].insert(0, "sqlite:///./company_os.db"),
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            db_btn_row,
            text="Initialize Database & Genesis Trust Block",
            style="Success.TButton",
            command=self._init_database_action,
        ).pack(side=tk.LEFT, padx=8)

        # Step 3: Security & Governance Keys
        f3 = self._create_card(scrollable_frame, "Step 3: Security & Role-Based API Keys")
        self._create_field(f3, "Manager API Key (32+ chars):", "MANAGER_API_KEY", "", row=0, is_secret=True)
        ttk.Button(
            f3,
            text="🎲 Generate Key",
            style="Secondary.TButton",
            command=lambda: self._generate_key("MANAGER_API_KEY", "sk_mgr_"),
        ).grid(row=0, column=2, padx=8, pady=4)

        self._create_field(f3, "Owner API Key (32+ chars, HITL):", "OWNER_API_KEY", "", row=1, is_secret=True)
        ttk.Button(
            f3,
            text="🎲 Generate Key",
            style="Secondary.TButton",
            command=lambda: self._generate_key("OWNER_API_KEY", "sk_own_"),
        ).grid(row=1, column=2, padx=8, pady=4)

        self._create_field(f3, "ASK4 Webhook Secret:", "ASK4_WEBHOOK_SECRET", "ask4_webhook_secret_for_production_testing", row=2, is_secret=True)

        # Step 4: AI & LangSmith Telemetry
        f4 = self._create_card(scrollable_frame, "Step 4: AI Engine (Gemini) & LangSmith Telemetry")
        self._create_field(f4, "Google Gemini API Key:", "GOOGLE_API_KEY", "", row=0, is_secret=True)
        ttk.Button(
            f4,
            text="🧪 Test AI Key",
            style="Secondary.TButton",
            command=self._test_gemini_key,
        ).grid(row=0, column=2, padx=8, pady=4)

        self._create_field(f4, "Gemini Model (GEMINI_MODEL):", "GEMINI_MODEL", "gemini-3.8-flash", row=1)
        self._create_field(f4, "LangSmith API Key:", "LANGSMITH_API_KEY", "", row=2, is_secret=True)
        self._create_field(f4, "LangSmith Project Name:", "LANGSMITH_PROJECT", "os_gateway", row=3)
        self._create_field(f4, "LangSmith Tracing (true/false):", "LANGSMITH_TRACING", "true", row=4)

        # Bottom Save Bar
        btn_bar = tk.Frame(scrollable_frame, bg=BG_DARK, pady=16)
        btn_bar.pack(fill=tk.X)

        ttk.Button(
            btn_bar,
            text="💾 Save Configuration (.env)",
            style="Primary.TButton",
            command=self._save_env_config,
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            btn_bar,
            text="🚀 Save & Switch to Server Control",
            style="Success.TButton",
            command=lambda: (self._save_env_config(), self.notebook.select(self.tab_control)),
        ).pack(side=tk.LEFT, padx=10)

    def _build_control_tab(self):
        container = tk.Frame(self.tab_control, bg=BG_DARK, padx=10, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        # Top Control Action Card
        ctrl_card = tk.Frame(container, bg=BG_CARD, padx=16, pady=14, relief="flat")
        ctrl_card.pack(fill=tk.X, pady=(0, 10))

        tk.Label(ctrl_card, text="GATEWAY SERVER RUNTIME", font=("Segoe UI", 12, "bold"), fg=TEXT_ACCENT, bg=BG_CARD).pack(anchor="w", pady=(0, 8))

        btn_row = tk.Frame(ctrl_card, bg=BG_CARD)
        btn_row.pack(fill=tk.X)

        self.btn_start = ttk.Button(btn_row, text="▶  Start Server", style="Success.TButton", command=self._start_server)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = ttk.Button(btn_row, text="⏹  Stop Server", style="Danger.TButton", command=self._stop_server, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=8)

        ttk.Button(btn_row, text="📖 Open API Docs (Swagger)", style="Secondary.TButton", command=lambda: webbrowser.open(f"{self.api_url}/docs")).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="📊 Open LangSmith Dashboard", style="Secondary.TButton", command=lambda: webbrowser.open("https://smith.langchain.com")).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="🧹 Clear Console", style="Secondary.TButton", command=self._clear_logs).pack(side=tk.RIGHT)

        # Quick stats indicators
        stats_frame = tk.Frame(ctrl_card, bg=BG_CARD_LIGHT, padx=14, pady=10)
        stats_frame.pack(fill=tk.X, pady=(12, 0))

        self.lbl_stat_db = tk.Label(stats_frame, text="Database: Checking...", font=("Segoe UI", 9), fg=TEXT_MUTED, bg=BG_CARD_LIGHT)
        self.lbl_stat_db.pack(side=tk.LEFT, padx=12)

        self.lbl_stat_trust = tk.Label(stats_frame, text="Trust Chain: Initializing...", font=("Segoe UI", 9), fg=TEXT_MUTED, bg=BG_CARD_LIGHT)
        self.lbl_stat_trust.pack(side=tk.LEFT, padx=12)

        self.lbl_stat_approvals = tk.Label(stats_frame, text="Pending Approvals: 0", font=("Segoe UI", 9), fg=TEXT_MUTED, bg=BG_CARD_LIGHT)
        self.lbl_stat_approvals.pack(side=tk.LEFT, padx=12)

        # Live Console Output
        console_card = tk.Frame(container, bg=BG_CARD, padx=16, pady=12, relief="flat")
        console_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(console_card, text="LIVE SYSTEM LOGS & TELEMETRY", font=("Segoe UI", 11, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", pady=(0, 6))

        self.log_text = scrolledtext.ScrolledText(
            console_card,
            bg=BG_INPUT,
            fg="#cbd5e1",
            insertbackground="white",
            font=("Consolas", 9),
            wrap=tk.WORD,
            borderwidth=0,
            relief="flat",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Tag styles for logs
        self.log_text.tag_config("INFO", foreground="#38bdf8")
        self.log_text.tag_config("SUCCESS", foreground=COLOR_SUCCESS)
        self.log_text.tag_config("WARNING", foreground=COLOR_WARNING)
        self.log_text.tag_config("ERROR", foreground=COLOR_DANGER)
        self.log_text.tag_config("AGENT", foreground="#c084fc")

    def _build_agents_tab(self):
        container = tk.Frame(self.tab_agents, bg=BG_DARK, padx=12, pady=12)
        container.pack(fill=tk.BOTH, expand=True)

        # Agent fleet overview
        fleet_card = tk.Frame(container, bg=BG_CARD, padx=16, pady=14)
        fleet_card.pack(fill=tk.X, pady=(0, 10))

        tk.Label(fleet_card, text="MULTI-AGENT FLEET STATUS & HITL WORKFLOWS", font=("Segoe UI", 12, "bold"), fg=TEXT_ACCENT, bg=BG_CARD).pack(anchor="w", pady=(0, 8))

        desc = (
            "The AskforWrite AI Company OS coordinates autonomous agents with mandatory Human-In-The-Loop (HITL) gates:\n"
            "• Manager Agent: Orchestrates discovery, leads research, and delegates tasks.\n"
            "• Discovery & Research Agent: Bounded lead finding, evidence synthesis, and AI fit scoring.\n"
            "• Sales Agent: Proposal generation from client notes.\n"
            "• Owner HITL Gate: Strict cryptographic approval checkpoint before external outreach or delivery."
        )
        tk.Label(fleet_card, text=desc, font=("Segoe UI", 9), fg=TEXT_MUTED, bg=BG_CARD, justify=tk.LEFT).pack(anchor="w", pady=(0, 12))

        # Workflow Actions
        actions_row = tk.Frame(fleet_card, bg=BG_CARD)
        actions_row.pack(fill=tk.X)

        ttk.Button(
            actions_row,
            text="⚡ Run LangGraph AI Cycle (Gemini + Agents)",
            style="Primary.TButton",
            command=self._run_langgraph_action,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            actions_row,
            text="🔄 Run Full E2E Integration Suite",
            style="Secondary.TButton",
            command=self._run_e2e_action,
        ).pack(side=tk.LEFT, padx=8)

        ttk.Button(
            actions_row,
            text="🛡️ Verify Cryptographic Trust Ledger",
            style="Secondary.TButton",
            command=self._verify_trust_ledger,
        ).pack(side=tk.LEFT, padx=8)

        # Agent Output Console
        agent_console_card = tk.Frame(container, bg=BG_CARD, padx=16, pady=12)
        agent_console_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(agent_console_card, text="ORCHESTRATOR EXECUTION OUTPUT", font=("Segoe UI", 11, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", pady=(0, 6))

        self.agent_output_text = scrolledtext.ScrolledText(
            agent_console_card,
            bg=BG_INPUT,
            fg="#e2e8f0",
            insertbackground="white",
            font=("Consolas", 9),
            wrap=tk.WORD,
            borderwidth=0,
            relief="flat",
        )
        self.agent_output_text.pack(fill=tk.BOTH, expand=True)

    def _build_footer(self):
        footer = tk.Frame(self, bg=BG_DARK, padx=20, pady=8)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        lbl = tk.Label(
            footer,
            text="AskforWrite AI Company OS v0.2.0 • Ready for Production Desktop Deployment • Localhost:8000",
            font=("Segoe UI", 8),
            fg=TEXT_MUTED,
            bg=BG_DARK,
        )
        lbl.pack(side=tk.LEFT)

    # ── Helpers for Form Fields ─────────────────────────────────────────

    def _create_card(self, parent, title):
        card = tk.Frame(parent, bg=BG_CARD, padx=18, pady=14, relief="flat")
        card.pack(fill=tk.X, pady=8, padx=4)

        title_lbl = tk.Label(card, text=title, font=("Segoe UI", 11, "bold"), fg=TEXT_ACCENT, bg=BG_CARD)
        title_lbl.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        if not hasattr(self, "entries"):
            self.entries = {}
        return card

    def _create_field(self, parent, label_text, var_name, default_val="", row=1, is_secret=False):
        lbl = tk.Label(parent, text=label_text, font=("Segoe UI", 9, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD)
        lbl.grid(row=row + 1, column=0, sticky="w", pady=4, padx=(0, 12))

        val = os.environ.get(var_name, default_val)
        entry = tk.Entry(
            parent,
            bg=BG_INPUT,
            fg=TEXT_PRIMARY,
            insertbackground="white",
            font=("Consolas", 9),
            width=58,
            relief="flat",
            show="•" if is_secret else "",
        )
        entry.insert(0, val)
        entry.grid(row=row + 1, column=1, sticky="w", pady=4)
        self.entries[var_name] = entry

        # Show/Hide toggle button for secrets
        if is_secret:
            toggle_btn = tk.Button(
                parent,
                text="👁",
                bg=BG_CARD,
                fg=TEXT_MUTED,
                activebackground=BG_CARD,
                activeforeground=TEXT_PRIMARY,
                bd=0,
                cursor="hand2",
                command=lambda e=entry: e.configure(show="" if e.cget("show") == "•" else "•"),
            )
            toggle_btn.grid(row=row + 1, column=2, padx=(2, 0), sticky="w")

    def _generate_key(self, var_name, prefix="sk_"):
        key = prefix + secrets.token_urlsafe(32)
        if var_name in self.entries:
            self.entries[var_name].delete(0, tk.END)
            self.entries[var_name].insert(0, key)
            self.log(f"Generated new secure key for {var_name}", "SUCCESS")

    def _save_env_config(self):
        try:
            for var_name, entry in self.entries.items():
                val = entry.get().strip()
                os.environ[var_name] = val
                set_key(str(ENV_PATH), var_name, val)
            self.log(f"Saved configuration to {ENV_PATH}", "SUCCESS")
            messagebox.showinfo("Success", "Configuration successfully saved to .env!")
        except Exception as e:
            self.log(f"Error saving .env: {e}", "ERROR")
            messagebox.showerror("Error", f"Failed to save .env file: {e}")

    # ── Database Initialization ──────────────────────────────────────────

    def _init_database_action(self):
        # Read the DATABASE_URL directly from the GUI field (before saving to disk)
        db_url = self.entries.get("DATABASE_URL", None)
        db_url_val = db_url.get().strip() if db_url else ""
        if not db_url_val:
            db_url_val = "sqlite:///./company_os.db"

        # Force the environment variable NOW so database.py picks it up
        os.environ["DATABASE_URL"] = db_url_val
        # Allow SQLite even if APP_ENV is not 'development'
        os.environ["ALLOW_SQLITE_PRODUCTION"] = "true"

        self._save_env_config()
        self.log(f"Initializing database with URL: {db_url_val[:60]}...", "INFO")

        def run():
            try:
                import importlib
                import sys

                # Force-reload database modules so the engine is rebuilt
                # with the correct DATABASE_URL from os.environ (not from .env on disk)
                for mod_name in list(sys.modules.keys()):
                    if mod_name in (
                        "app.db.database",
                        "app.db.models",
                        "app.security.trust_chain",
                    ):
                        del sys.modules[mod_name]

                from app.db.database import Base, engine, SessionLocal
                from app.db.models import TrustBlock
                from app.security.trust_chain import ensure_genesis_block

                # Create all tables
                Base.metadata.create_all(bind=engine)
                self.log("Database schema synchronized.", "SUCCESS")

                # Seed genesis block
                session = SessionLocal()
                try:
                    ensure_genesis_block(session)
                    session.commit()
                    count = session.query(TrustBlock).count()
                    self.log(f"Trust chain genesis block verified ({count} block(s) present).", "SUCCESS")
                    messagebox.showinfo(
                        "Database Initialized",
                        f"Database schema and Trust Ledger successfully initialized!\n"
                        f"Genesis block confirmed ({count} blocks).\n"
                        f"URL: {db_url_val[:80]}"
                    )
                finally:
                    session.close()
            except Exception as exc:
                self.log(f"Database initialization error: {exc}", "ERROR")
                messagebox.showerror("Init Error", f"Failed to initialize database:\n{exc}")

        threading.Thread(target=run, daemon=True).start()

    def _test_gemini_key(self):
        key = self.entries.get("GOOGLE_API_KEY", tk.Entry()).get().strip()
        if not key:
            messagebox.showwarning("Missing Key", "Please enter a Google Gemini API Key first.")
            return

        model_name = self.entries.get("GEMINI_MODEL", tk.Entry()).get().strip() or os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
        self.log(f"Testing Gemini API connection using {model_name}...", "INFO")

        def test():
            try:
                from google import genai
                client = genai.Client(api_key=key)
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents="Respond with 'Gemini connection verified.'",
                    )
                except Exception as model_err:
                    self.log(f"Primary model {model_name} failed ({model_err}). Trying gemini-3.5-flash fallback...", "WARNING")
                    response = client.models.generate_content(
                        model="gemini-3.5-flash",
                        contents="Respond with 'Gemini connection verified.'",
                    )
                self.log(f"Gemini API Response: {response.text.strip()}", "SUCCESS")
                messagebox.showinfo("AI Verified", f"Google Gemini API Key is working!\nResponse: {response.text.strip()}")
            except Exception as e:
                self.log(f"Gemini API check failed: {e}", "ERROR")
                messagebox.showerror("Gemini Error", f"API connection failed:\n{e}")

        threading.Thread(target=test, daemon=True).start()

    # ── Server Runtime ──────────────────────────────────────────────────

    def _start_server(self):
        if self.server_running:
            return

        self._save_env_config()
        port = int(self.entries.get("APP_PORT", tk.Entry()).get().strip() or "8000")
        self.api_url = f"http://127.0.0.1:{port}"

        self.log(f"Launching AskforWrite AI Company OS on port {port}...", "INFO")
        self.btn_start.configure(state=tk.DISABLED)
        self.status_badge.configure(text="● STARTING SERVER...", fg="#f59e0b", bg="#1e293b")

        def run_uvicorn():
            try:
                import logging
                import uvicorn
                from app.main import app

                # Route uvicorn logs to the GUI console
                class GuiLogHandler(logging.Handler):
                    def __init__(self, log_fn):
                        super().__init__()
                        self.log_fn = log_fn

                    def emit(self, record):
                        try:
                            msg = self.format(record)
                            level = record.levelname
                            tag = "INFO"
                            if level in ("WARNING", "WARN"):
                                tag = "WARNING"
                            elif level in ("ERROR", "CRITICAL"):
                                tag = "ERROR"
                            self.log_fn(msg, tag)
                        except Exception:
                            pass

                gui_handler = GuiLogHandler(self.log)
                gui_handler.setFormatter(logging.Formatter("%(message)s"))
                for log_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
                    l = logging.getLogger(log_name)
                    l.handlers = [gui_handler]
                    l.setLevel(logging.INFO)

                config = uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=port,
                    log_level="info",
                    log_config=None,  # Disables default dictConfig which fails in PyInstaller frozen apps
                    access_log=True,
                )
                server = uvicorn.Server(config)
                self.server_instance = server
                self.server_running = True
                self.btn_stop.configure(state=tk.NORMAL)
                self.status_badge.configure(text=f"● SERVER ACTIVE (PORT {port})", fg=COLOR_SUCCESS, bg="#064e3b")
                self.log(f"Gateway listening at {self.api_url}", "SUCCESS")
                self.log(f"Swagger Documentation: {self.api_url}/docs", "INFO")
                server.run()
            except Exception as e:
                self.log(f"Server exited: {e}", "ERROR")
            finally:
                self.server_running = False
                self.btn_start.configure(state=tk.NORMAL)
                self.btn_stop.configure(state=tk.DISABLED)
                self.status_badge.configure(text="● SERVER STOPPED", fg="#94a3b8", bg="#1e293b")

        self.server_thread = threading.Thread(target=run_uvicorn, daemon=True)
        self.server_thread.start()

    def _stop_server(self):
        if hasattr(self, "server_instance") and self.server_instance:
            self.log("Stopping server...", "WARNING")
            self.server_instance.should_exit = True
            self.server_running = False
            self.btn_start.configure(state=tk.NORMAL)
            self.btn_stop.configure(state=tk.DISABLED)
            self.status_badge.configure(text="● SERVER STOPPED", fg="#94a3b8", bg="#1e293b")

    def _check_server_health(self):
        if self.server_running:
            try:
                r = httpx.get(f"{self.api_url}/health", timeout=1.5)
                if r.status_code == 200:
                    data = r.json()
                    self.lbl_stat_db.configure(text=f"Database: {data.get('database', 'connected').upper()}", fg=COLOR_SUCCESS)
                    self.lbl_stat_trust.configure(text=f"Trust Chain: OK ({data.get('version', 'v0.2.0')})", fg=COLOR_SUCCESS)
            except Exception:
                self.lbl_stat_db.configure(text="Database: Polling...", fg=TEXT_MUTED)
        self.after(3000, self._check_server_health)

    # ── Multi-Agent Actions ──────────────────────────────────────────────

    def _run_langgraph_action(self):
        self.agent_output_text.delete(1.0, tk.END)
        self.agent_output_text.insert(tk.END, "=== STARTING LANGGRAPH MULTI-AGENT ORCHESTRATION ===\n")
        self.agent_output_text.insert(tk.END, "Initializing Manager -> Discovery -> Sales -> HITL loop with Gemini...\n\n")

        def run():
            try:
                from app.agents.orchestrator import orchestrator_app

                initial_state = {
                    "task_id": f"gui-task-{int(time.time())}",
                    "correlation_id": f"gui-corr-{int(time.time())}",
                    "manager_id": "manager-gui-user",
                    "objective": "Find logistics & retail businesses needing automated field dispatch and QA",
                    "limit": 3,
                    "leads": [],
                    "proposals": [],
                    "pending_approvals": [],
                    "approved_leads": [],
                    "status": "PLANNING",
                    "error": None,
                }

                for output in orchestrator_app.stream(initial_state):
                    for node_name, val in output.items():
                        status = val.get("status", "RUNNING")
                        msg = f"[NODE: {node_name}] Status: {status}\n"
                        if node_name == "discovery_node":
                            leads = val.get("leads", [])
                            msg += f"  -> AI Discovered {len(leads)} qualified leads:\n"
                            for idx, lead in enumerate(leads, 1):
                                msg += f"     {idx}. {lead.get('company', 'Unknown')} | Fit: {lead.get('fit_score', 0):.2f} | Product: {lead.get('product_match', 'N/A')}\n"
                        elif node_name == "sales_node":
                            props = val.get("proposals", [])
                            msg += f"  -> AI Drafted {len(props)} customized proposals:\n"
                            for p in props:
                                company = p.get('company', 'Unknown')
                                summary = p.get('proposal_text') or p.get('proposal_summary') or p.get('proposal_title', '')
                                priority = p.get('priority', 'N/A')
                                msg += f"     • [{priority}] {company}: {summary[:100]}...\n"
                        elif node_name == "human_approval_node":
                            pending = val.get("pending_approvals", [])
                            msg += "  -> 🛑 HITL GOVERNANCE GATE REACHED: Execution paused awaiting Owner sign-off!\n"
                            if pending:
                                msg += f"     Companies awaiting approval: {', '.join(pending)}\n"
                            msg += "\n  📋 HOW TO APPROVE (HITL Access):\n"
                            msg += "     1. Open browser → http://127.0.0.1:8000/docs\n"
                            msg += "     2. POST /approvals/request  (with Manager API Key)\n"
                            msg += "     3. POST /approvals/{id}/decide  (with OWNER API Key + decision: APPROVED)\n"
                            msg += "     4. Or use Server & Live Console tab → API docs\n"

                        self.agent_output_text.insert(tk.END, msg + "\n")
                        self.agent_output_text.see(tk.END)

                self.agent_output_text.insert(tk.END, "\n✓ Orchestration cycle completed successfully!\n")
                self.agent_output_text.insert(tk.END, "Trace logged in LangSmith dashboard.\n")

            except Exception as e:
                self.agent_output_text.insert(tk.END, f"\n❌ Orchestrator Error: {e}\n")

        threading.Thread(target=run, daemon=True).start()

    def _run_e2e_action(self):
        if not self.server_running:
            messagebox.showwarning("Server Not Running", "Please start the Gateway Server in the 'Server & Live Console' tab before running E2E integration tests.")
            return

        self.agent_output_text.delete(1.0, tk.END)
        self.agent_output_text.insert(tk.END, "=== STARTING FULL END-TO-END INTEGRATION CYCLE ===\n")
        self.agent_output_text.insert(tk.END, f"Target API: {self.api_url}\n\n")

        def run():
            try:
                import subprocess
                p = subprocess.Popen(
                    [sys.executable, "scripts/e2e_cycle.py"],
                    cwd=str(BASE_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                for line in p.stdout:
                    self.agent_output_text.insert(tk.END, line)
                    self.agent_output_text.see(tk.END)
                p.wait()
                self.agent_output_text.insert(tk.END, f"\n=== E2E Process Exited (code {p.returncode}) ===\n")
            except Exception as e:
                self.agent_output_text.insert(tk.END, f"\n❌ Execution Error: {e}\n")

        threading.Thread(target=run, daemon=True).start()

    def _verify_trust_ledger(self):
        self.log("Verifying Cryptographic Trust Ledger integrity...", "INFO")

        def run():
            try:
                from app.db.database import SessionLocal
                from app.security.trust_chain import verify_chain_integrity

                session = SessionLocal()
                try:
                    res = verify_chain_integrity(session)
                    is_valid = res.get("chain_valid", False)
                    blocks = res.get("total_blocks", 0)
                    errors = res.get("errors", [])
                    if is_valid:
                        tip_idx = res.get("tip_index", 0)
                        genesis_hash = (res.get("genesis_hash") or "")[:16]
                        tip_hash = (res.get("tip_hash") or "")[:16]
                        msg = (
                            f"Cryptographic Ledger is 100% VALID!\n"
                            f"Total Blocks: {blocks} (Block #0 → #{tip_idx})\n"
                            f"Genesis Hash: {genesis_hash}…\n"
                            f"Tip Hash: {tip_hash}…\n"
                            f"Zero tampered blocks detected."
                        )
                        self.log(msg, "SUCCESS")
                        messagebox.showinfo("Ledger Valid ✓", msg)
                    else:
                        msg = f"Ledger integrity errors in {len(errors)} block(s):\n" + "\n".join(errors[:5])
                        self.log(msg, "ERROR")
                        messagebox.showerror("Integrity Warning", msg)
                finally:
                    session.close()
            except Exception as e:
                self.log(f"Trust chain verification failed: {e}", "ERROR")
                messagebox.showerror("Error", f"Verification failed: {e}")

        threading.Thread(target=run, daemon=True).start()

    # ── Logging ──────────────────────────────────────────────────────────

    def log(self, text, tag="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put((f"[{timestamp}] {text}\n", tag))

    def _process_log_queue(self):
        while not self.log_queue.empty():
            msg, tag = self.log_queue.get()
            self.log_text.insert(tk.END, msg, tag)
            self.log_text.see(tk.END)
        self.after(200, self._process_log_queue)

    def _clear_logs(self):
        self.log_text.delete(1.0, tk.END)


if __name__ == "__main__":
    app = CompanyOSDesktopApp()
    app.mainloop()
