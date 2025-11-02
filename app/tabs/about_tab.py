from __future__ import annotations
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextBrowser

ABOUT_HTML = r"""
<meta name="color-scheme" content="dark light">
<style>
  body { font-family: Segoe UI, Roboto, Arial; font-size: 14px; line-height: 1.45; margin: 0; padding: 0; }
  h1, h2, h3 { margin: 0.2em 0 0.4em; }
  h2 { font-size: 18px; }
  .muted { color: #AAA; }
  .wrap { padding: 10px 12px; }
  .box { border: 1px solid #3a3a3a; border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
  ul { margin: 6px 0 6px 18px; }
  a { color: #6aa9ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  code { background: #222; padding: 0 4px; border-radius: 4px; }
  .cols { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
  .small { font-size: 12px; }
</style>

<div class="wrap">
  <h2>Lies of P Save Editor - <span class="muted">v1.0 <b>(RELEASE!)</b></span></h2>
  <p>This save editor was created by <b>ProtoBuffers</b>.</p>

  <div class="box">
    <p><b>Credits</b></p>
    <ul>
      <li><b>ueSave</b> for GVAS compression/handling (this tool is basically a JSON editor sitting on top of ueSave).</li>
      <li>Naming / ID help: <b>method_dev</b>, <b>pj1980</b>, <b>AmericanDream91</b>.</li>
    </ul>

    <div class="cols">
      <div>
        <p class="small"><b>PS4 users:</b></p>
        <ul class="small">
          <li>Join Discord for free save decryption:<br>
            <a href="https://discord.gg/protobuffers" target="_blank">https://discord.gg/protobuffers</a></li>
        </ul>
      </div>

      <div>
        <p class="small"><b>Support:</b></p>
        <ul class="small">
          <li>PayPal: <a href="https://paypal.me/xcier" target="_blank">https://paypal.me/xcier</a></li>
          <li>Cash App: <code>$xcier</code></li>
          <li>YouTube / Instagram / TikTok: <b>protobuffers</b></li>
        </ul>

        <div class="small" style="margin-top:8px;">
          <p><b>Changelog</b></p>

          <p><b>0.5 → 1.0 (RELEASE!)</b></p>
          <ul>
            <li>General code cleanup / stability polish</li>
            <li>Added working Light / Dark Mode toggle (bottom right of the editor)</li>
            <li>Fast Travel tab now respects theme</li>
          </ul>

          <p><b>0.3 → 0.4 / 0.5 (beta)</b></p>
          <ul>
            <li>Rewrote load/save classes</li>
            <li>Backend cleanup / refactor</li>
          </ul>
        </div>
      </div>
    </div>
  </div>

  <div class="box">
    <p><b>Capabilities</b></p>
    <ul>
      <li>Edit player saves and <code>Account#</code> files.</li>
      <li><i>Account files can be edited to obtain all trophies without doing anything.</i></li>
    </ul>
    <p><b>Important:</b> Back up your <code>accountID</code> (it’s linked to your save string info). When importing with Ezwizard3, use <b>Advanced Mode Import</b>.</p>
  </div>

  <div class="box">
    <p><b>Included Features</b></p>
    <ul>
      <li>GUID Swapper (save account ID swapper)</li>
      <li>Play Time, Death Count, NG+ Completion Count</li>
      <li>Character Level, Ergo, Ergo needed for next level</li>
      <li>Humanity Level &amp; Humanity</li>
      <li>Starting Skill (balance / dexterity / strength)</li>
      <li>Total Damage Taken, Lamp (on/off)</li>
    </ul>

    <p><b>Stats &amp; Items</b></p>
    <ul>
      <li>All Primary/Second Stats <i>(attributes cap at 100; higher values render but may cause lag)</i></li>
      <li>In-game currencies / trade items</li>
      <li>Inventory Editor (add missing items / swap item count / equip)</li>
    </ul>

    <p><b>World / Progress</b></p>
    <ul>
      <li>Mission Editing</li>
      <li>Fast Travel / Location Data</li>
    </ul>

    <p><b>Tools</b></p>
    <ul>
      <li>JSON Editor (full decrypted save contents — <b>leave header alone</b>)</li>
      <li>JSON Converter</li>
      <li>Quick Cheats</li>
    </ul>
  </div>

  <div class="box">
    <p class="small">
      <b>Note:</b> This editor modifies save data directly. Always keep a backup of your original <code>.sav</code> and <code>Account#</code>
      before making changes.
    </p>
  </div>
</div>
"""

class AboutTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        view = QTextBrowser(self)
        view.setOpenExternalLinks(True)
        view.setHtml(ABOUT_HTML)
        layout.addWidget(view)
