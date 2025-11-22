from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextBrowser


class AboutTab(QWidget):
    """
    Simple QTextBrowser-based About page.

    - Respects dark / light theme via apply_theme(dark: bool)
    - Keeps all existing credits (ProtoBuffers, ueSave, method_dev, pj1980, AmericanDream91)
    - Uses high-contrast colors in both modes and accessible link colors.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)

        self.view = QTextBrowser(self)
        self.view.setOpenExternalLinks(True)
        self.view.setReadOnly(True)

        # Slightly bigger, clean font by default
        font = QFont()
        font.setPointSize(font.pointSize() + 1)
        self.view.setFont(font)

        layout.addWidget(self.view)

        self._dark_mode = True  # default; MainWindow will call apply_theme

        self._set_html()

    # ------------------------------------------------------------------ #
    # Theme handling                                                     #
    # ------------------------------------------------------------------ #
    def apply_theme(self, dark: bool) -> None:
        """
        Called from MainWindow._toggle_dark_mode(dark).

        We don't change the global palette here (that's MainWindow's job),
        we only adjust the QTextBrowser's background / text / link colors.
        """
        self._dark_mode = bool(dark)

        if dark:
            # Dark background, light text, soft link color
            self.view.setStyleSheet(
                """
                QTextBrowser {
                    background: #24262b;
                    color: #f3f5f8;
                    border: none;
                }
                QTextBrowser QScrollBar:vertical {
                    background: #24262b;
                }
                a {
                    color: #7ab4ff;
                    text-decoration: none;
                }
                a:hover {
                    color: #a8cfff;
                    text-decoration: underline;
                }
                """
            )
        else:
            # Light background, darker text, classic blue links
            self.view.setStyleSheet(
                """
                QTextBrowser {
                    background: #fafafa;
                    color: #151515;
                    border: none;
                }
                QTextBrowser QScrollBar:vertical {
                    background: #fafafa;
                }
                a {
                    color: #0645ad;
                    text-decoration: none;
                }
                a:hover {
                    color: #0b63d1;
                    text-decoration: underline;
                }
                """
            )

    # ------------------------------------------------------------------ #
    # Content                                                            #
    # ------------------------------------------------------------------ #
    def _set_html(self) -> None:
        """
        Static HTML content for the About page.
        You can tweak wording without worrying about theme – colors come
        from apply_theme().
        """
        html = """
        <html>
        <head>
            <style>
                body {
                    margin: 0;
                    padding: 0;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                    line-height: 1.5;
                    font-size: 10pt;
                }
                h1 {
                    margin-top: 0;
                    margin-bottom: 8px;
                    font-size: 14pt;
                }
                h2 {
                    margin-top: 16px;
                    margin-bottom: 4px;
                    font-size: 12pt;
                }
                h3 {
                    margin-top: 12px;
                    margin-bottom: 2px;
                    font-size: 11pt;
                }
                p {
                    margin: 4px 0;
                }
                ul {
                    margin: 4px 0 4px 20px;
                    padding: 0;
                }
                li {
                    margin: 2px 0;
                }
                .small {
                    font-size: 8.5pt;
                    opacity: 0.85;
                }
                .mono {
                    font-family: "Consolas", "Fira Code", monospace;
                }
            </style>
        </head>
        <body>
            <h1>Lies of P Save Editor V1.01</h1>
            <p>This save editor was created by <b>ProtoBuffers</b>.<br>
               It is an offline JSON-based editor that sits on top of <b>ueSave</b> and similar tooling.</p>

            <h2>Credits</h2>
            <ul>
                <li><b>ueSave</b> – for GVAS compression / handling. This editor is basically a JSON front-end sitting on top of ueSave.</li>
                <li>Naming / ID help:
                    <b>method_dev</b>, <b>pj1980</b>, <b>AmericanDream91</b>.</li>
            </ul>

            <h2>PS4 Users</h2>
            <ul>
                <li>Join Discord for free save decryption:<br>
                    <a href="https://discord.gg/protobuffers">https://discord.gg/protobuffers</a>
                </li>
            </ul>

            <h2>Support</h2>
            <ul>
                <li>PayPal: <a href="https://paypal.me/xcier">https://paypal.me/xcier</a></li>
                <li>Cash App: <span class="mono">$xcier</span></li>
                <li>YouTube / Instagram / TikTok: <b>protobuffers</b></li>
            </ul>

            <h2>Changelog (1.01)</h2>
            <ul>
                <li>Updated JSON tab to include the ability to load a second save for easy data comparing.</li>
                <li>Cleaned Mission tab updated to load faster.</li>
                <li>Updated window title to display correct version.</li>
                <li>Fixed DarkMode/LightMode improper display.</li>
            </ul>

            <h2>Quick Start</h2>
            <ul>
                <li>Go to <b>File</b> → <b>Open…</b> and select a <span class="mono">.sav</span> or JSON file.</li>
                <li>Edit values in the tabs: Character, Stats, Currency, Inventory, Missions, etc.</li>
                <li>Use <b>Save JSON As…</b> to keep readable backups of your changes.</li>
                <li>Use <b>Save Sav As…</b> to build a new game save via <span class="mono">uesave.exe</span>.</li>
            </ul>
            <p class="small">
                Tip: Always work on copies of your saves. If anything breaks, revert to your backup.
            </p>

            <h2>Capabilities</h2>
            <ul>
                <li>Edit player saves and account files.</li>
                <li><b>Account files can be edited to obtain all trophies without doing anything (use with caution and always keep backups).</b></li>
            </ul>

            <p><b>Important:</b> Back up your account ID and original saves before making changes.
            If something goes wrong when importing with E\x32Wizard3, use <b>Advanced Mode Import</b>.</p>

            <h2>Included Features</h2>
            <ul>
                <li>GUID Swapper (save account ID swapper).</li>
                <li>Play Time, Death Count, NG+ Completion Count.</li>
                <li>Character Level, Ergo, Ergo needed for next level.</li>
                <li>Humanity Level &amp; Humanity.</li>
                <li>Starting Skill (balance / dexterity / strength).</li>
                <li>Total Damage Taken, Lamp (on/off).</li>
            </ul>

            <h3>Stats &amp; Items</h3>
            <ul>
                <li>All primary / secondary stats (attributes cap at 100; higher values render but may cause lag).</li>
                <li>In-game currencies / trade items.</li>
                <li>Inventory editor (add missing items / swap item count / equip).</li>
            </ul>

            <h3>Cheats Overview</h3>
            <ul>
                <li><b>Godmode</b> – makes the character extremely hard to kill.</li>
                <li><b>Insane Stats</b> – boosts core attributes to very high values.</li>
                <li><b>Max Currency</b> – tops up major currencies to high, safe amounts.</li>
                <li><b>Unlock Locations</b> – unlocks or reveals fast-travel spots.</li>
                <li><b>Plat Helpers</b> – tweaks flags related to trophy runs.</li>
            </ul>

            <p class="small">
                These are powerful edits. Always keep an original backup in case you want to go back.
            </p>
        </body>
        </html>
        """
        self.view.setHtml(html)
