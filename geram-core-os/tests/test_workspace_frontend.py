"""Framework-free checks for the Monaco workspace editor integration."""

import re
import subprocess
import unittest

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_JS = ROOT / "static/workspace.js"
MONACO_JS = ROOT / "static/monaco-editor.js"
ARES_JS = ROOT / "static/ares-workspace.js"
INLINE_AI_JS = ROOT / "static/inline-ai.js"
INDEX_HTML = ROOT / "static/index.html"
STYLE_CSS = ROOT / "static/style.css"


class IdAndLabelParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.labels = []

    def handle_starttag(self, _tag, attributes):
        values = dict(attributes)
        if "id" in values:
            self.ids.append(values["id"])
        if "for" in values:
            self.labels.append(values["for"])


def run_node(source):
    completed = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise AssertionError("Workspace JavaScript state check failed")


class WorkspaceFrontendStateTests(unittest.TestCase):
    def test_successful_save_clears_modified_state(self):
        run_node(
            "const W=require('./static/workspace.js');"
            "const s=new W.TemporaryEditorState();"
            "s.load({path:'a.py',content:'old',version:'v1'});"
            "s.edit('new');const snap=s.beginSave();s.finishSave(snap,'v2');"
            "if(s.modified||s.saving||s.version!=='v2')process.exit(1);"
        )

    def test_failed_save_preserves_modified_content(self):
        run_node(
            "const W=require('./static/workspace.js');"
            "const s=new W.TemporaryEditorState();"
            "s.load({path:'a.py',content:'old',version:'v1'});"
            "s.edit('local');s.beginSave();s.failSave('save_failed');"
            "if(!s.modified||s.currentContent!=='local'||s.saving)process.exit(1);"
        )

    def test_conflict_preserves_local_content(self):
        run_node(
            "const W=require('./static/workspace.js');"
            "const s=new W.TemporaryEditorState();"
            "s.load({path:'a.py',content:'old',version:'v1'});"
            "s.edit('local');s.beginSave();s.failSave('version_conflict');"
            "if(s.currentContent!=='local'||!s.modified||s.saveError!=='version_conflict')process.exit(1);"
        )

    def test_opening_another_file_with_changes_requests_confirmation(self):
        run_node(
            "const W=require('./static/workspace.js');let asked=0;"
            "const s=new W.TemporaryEditorState(()=>{asked++;return false;});"
            "s.load({path:'a.py',content:'old',version:'v1'});s.edit('local');"
            "if(s.canOpen('b.py')||asked!==1||!s.canOpen('a.py'))process.exit(1);"
        )

    def test_empty_file_state_is_supported(self):
        run_node(
            "const W=require('./static/workspace.js');"
            "const s=new W.TemporaryEditorState();"
            "s.load({path:'empty.txt',content:'',version:'v'});"
            "if(s.currentContent!==''||s.modified)process.exit(1);"
        )

    def test_pending_changes_survive_switching_models(self):
        run_node(
            "const W=require('./static/workspace.js');let asked=0;"
            "const s=new W.TemporaryEditorState(()=>{asked++;return true;});"
            "s.load({path:'a.py',content:'alpha',version:'a1'});s.edit('alpha local');"
            "if(!s.canOpen('b.js'))process.exit(1);"
            "s.load({path:'b.js',content:'beta',version:'b1'});s.edit('beta local');"
            "s.activate('a.py');"
            "if(asked!==1||s.currentContent!=='alpha local'||!s.modified)process.exit(1);"
        )

    def test_save_result_updates_its_document_even_after_switch(self):
        run_node(
            "const W=require('./static/workspace.js');"
            "const s=new W.TemporaryEditorState(()=>true);"
            "s.load({path:'a.py',content:'old',version:'a1'});s.edit('saved');"
            "const snap=s.beginSave();"
            "s.load({path:'b.js',content:'beta',version:'b1'});"
            "s.finishSave(snap,'a2');s.activate('a.py');"
            "if(s.modified||s.saving||s.version!=='a2'||s.savedContent!=='saved')process.exit(1);"
        )

    def test_destroy_releases_document_state(self):
        run_node(
            "const W=require('./static/workspace.js');"
            "const s=new W.TemporaryEditorState();"
            "s.load({path:'a.py',content:'safe',version:'v'});s.destroy();"
            "if(s.activePath!==''||s.documents.size!==0)process.exit(1);"
        )

    def test_api_save_uses_existing_workspace_contract(self):
        run_node(
            "const W=require('./static/workspace.js');let seen;"
            "const api=new W.WorkspaceApi((url,opt)=>{seen={url,opt};return Promise.resolve({ok:true,json:()=>Promise.resolve({version:'n'})});});"
            "api.save({path:'a.py',content:'text',baseVersion:'v'}).then(()=>{"
            "const body=JSON.parse(seen.opt.body);"
            "if(seen.url!=='/api/workspace/file'||seen.opt.method!=='PUT'||body.path!=='a.py'||body.content!=='text'||body.base_version!=='v')process.exit(1);"
            "}).catch(()=>process.exit(1));"
        )

    def test_malicious_filename_is_rendered_only_as_text(self):
        run_node(
            "const W=require('./static/workspace.js');"
            "const button={style:{},setAttribute(){},addEventListener(){}};"
            "const doc={createElement(){return button;}};"
            "const name='<img src=x onerror=alert(1)>';"
            "const result=W.createTreeButton(doc,{type:'file',name,path:'safe.txt',depth:1,editable:true},()=>{});"
            "if(result.textContent!=='· '+name||Object.prototype.hasOwnProperty.call(result,'innerHTML'))process.exit(1);"
        )


class WorkspaceFrontendStaticTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKSPACE_JS.read_text(encoding="utf-8")
        self.monaco_source = MONACO_JS.read_text(encoding="utf-8")
        self.ares_source = ARES_JS.read_text(encoding="utf-8")
        self.inline_ai_source = INLINE_AI_JS.read_text(encoding="utf-8")
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_names_and_errors_use_text_apis_not_html_injection(self):
        self.assertNotIn("innerHTML", self.source)
        self.assertNotIn("innerHTML", self.monaco_source)
        self.assertNotIn("innerHTML", self.ares_source)
        self.assertIn("button.textContent", self.source)
        self.assertIn("statusElement.textContent", self.source)

    def test_ctrl_and_cmd_s_route_to_save(self):
        self.assertIn("event.ctrlKey || event.metaKey", self.source)
        self.assertIn("event.preventDefault()", self.source)
        self.assertIn("saveActive()", self.source)

    def test_reopening_active_file_does_not_reload_and_discard_changes(self):
        self.assertIn("if (state.activePath === path)", self.source)
        self.assertIn("editorReady.then(function(adapter) { adapter.focus(); });", self.source)
        self.assertIn("if (state.has(path))", self.source)

    def test_workspace_content_is_not_persisted_or_logged(self):
        combined = self.source + "\n" + self.monaco_source + "\n" + self.ares_source
        forbidden = (
            "localStorage",
            "sessionStorage",
            "indexedDB",
            "document.cookie",
            "caches.",
            "console.",
        )
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, combined)

    def test_no_remote_resource_urls_or_google_fonts_remain(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                INDEX_HTML,
                STYLE_CSS,
                WORKSPACE_JS,
                MONACO_JS,
                ARES_JS,
                ROOT / "static/script.js",
            )
        )
        self.assertIsNone(
            re.search(
                r"(?:src|href)=[\"']https?://|url\([\"']?https?://",
                combined,
                flags=re.IGNORECASE,
            )
        )
        self.assertNotIn("fonts.googleapis.com", combined)

    def test_monaco_adapter_is_separate_from_api_transport(self):
        self.assertIn("function TemporaryEditorState", self.source)
        self.assertIn("function WorkspaceApi", self.source)
        self.assertNotIn("fetch(", self.monaco_source)
        self.assertIn("function MonacoEditorAdapter", self.monaco_source)
        self.assertIn("function TextareaEditorAdapter", self.monaco_source)
        self.assertIn("TemporaryEditorState: TemporaryEditorState", self.source)
        self.assertIn("WorkspaceApi: WorkspaceApi", self.source)

    def test_monaco_workers_and_loader_are_local(self):
        self.assertIn("var MONACO_BASE = '/vendor/monaco/vs'", self.monaco_source)
        self.assertIn("/base/worker/workerMain.js", self.monaco_source)
        self.assertNotRegex(self.monaco_source, r"https?://|(?:unpkg|jsdelivr|cdnjs)")
        self.assertIn('src="/vendor/monaco/vs/loader.js"', self.html)
        self.assertIn('href="/vendor/monaco/vs/editor/editor.main.css"', self.html)

    def test_fallback_is_hidden_until_monaco_initialization_fails(self):
        self.assertRegex(
            self.html,
            r'<textarea[^>]+id="workspaceTexto"[^>]+hidden',
        )
        self.assertIn("new TextareaEditorAdapter(options)", self.monaco_source)
        self.assertIn("container.hidden = true", self.monaco_source)

    def test_ares_proposals_require_review_and_explicit_actions(self):
        self.assertIn("/api/ares/proposals", self.ares_source)
        self.assertIn("/api/ares/proposals/approve", self.ares_source)
        self.assertIn("/api/ares/proposals/apply", self.ares_source)
        self.assertIn("approval: true", self.ares_source)
        self.assertIn("var approval = null", self.ares_source)
        self.assertIn("Approve proposal", self.ares_source)
        self.assertIn("Click Apply proposal", self.ares_source)
        self.assertLess(
            self.ares_source.index("if (approval)"),
            self.ares_source.index("fetch('/api/ares/proposals/apply'"),
        )
        self.assertIn("Review the diff before applying it.", self.ares_source)
        self.assertIn("controller.hasLocalChanges", self.ares_source)
        self.assertNotIn("eval(", self.ares_source)
        self.assertNotIn("subprocess", self.ares_source)

    def test_ares_diff_uses_safe_text_rendering_and_memory_only_state(self):
        self.assertIn("textContent", self.ares_source)
        self.assertIn("String(data.diff || '').split", self.ares_source)
        self.assertNotIn("original_files", self.ares_source)
        self.assertNotIn("localStorage", self.ares_source)
        self.assertNotIn("sessionStorage", self.ares_source)
        self.assertNotIn("console.", self.ares_source)

    def test_ares_controls_have_accessible_labels_and_limits(self):
        for required in (
            "workspaceAresInstruction",
            "workspaceAresAdd",
            "workspaceAresRequest",
            "workspaceAresApply",
            "workspaceAresReject",
            "workspaceAresDiff",
        ):
            self.assertIn(required, self.html)
        self.assertIn('maxlength="4000"', self.html)
        self.assertIn("Up to 3 files and 512 KiB", self.html)

    def test_workspace_controls_have_unique_ids_and_valid_labels(self):
        parser = IdAndLabelParser()
        parser.feed(self.html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for target in parser.labels:
            self.assertIn(target, parser.ids)
        for required in (
            "workspacePanel",
            "workspaceArbol",
            "workspaceMonaco",
            "workspaceTexto",
            "workspaceGuardar",
        ):
            self.assertIn(required, parser.ids)

    def test_settings_has_sidebar_provider_directory_and_extensible_integrations(self):
        script = (ROOT / "static/script.js").read_text(encoding="utf-8")
        style = STYLE_CSS.read_text(encoding="utf-8")
        self.assertIn("itemAi.dataset.configView = 'ai'", script)
        self.assertIn("item.dataset.configView = 'integrations'", script)
        self.assertIn('data-config-view="geram"', self.html)
        self.assertIn("configProviderDirectory", script)
        self.assertIn("At least one AI provider is required", script)
        self.assertIn("Recommended · free tier", script)
        self.assertIn("ollama", script)
        self.assertNotIn("providerId === 'ollama' || vistos", script)
        for field in (
            "TELEGRAM_BOT_TOKEN",
            "NOTION_API_KEY",
            "GOOGLE_CALENDAR_ACCESS_TOKEN",
            "SPOTIFY_ACCESS_TOKEN",
            "OBSIDIAN_VAULT_PATH",
        ):
            self.assertIn(field, script)
        self.assertIn(".config-sidebar", style)

    def test_frontend_payload_never_places_content_in_dom_metadata(self):
        self.assertNotRegex(self.source, r"dataset\.[A-Za-z]+\s*=\s*(?:file|snapshot)\.content")
        self.assertNotIn("setAttribute('data-content'", self.source)

    def test_profile_switch_preserves_workspace_and_controls_ares_panel(self):
        script = (ROOT / "static/script.js").read_text(encoding="utf-8")
        style = STYLE_CSS.read_text(encoding="utf-8")
        profile_logic = script[
            script.index("function activarPerfil(perfil)"):
            script.index("// Abre el workspace disparando")
        ]
        self.assertIn('class="modo-dev perfil-ares"', self.html)
        self.assertIn('data-profile="ares"', self.html)
        self.assertIn("function activarPerfil(perfil)", script)
        self.assertIn("panelAres.setAttribute('aria-hidden'", script)
        self.assertIn("GeramWorkspaceController.editorReady", script)
        self.assertIn("adapter.layout()", script)
        self.assertNotIn("wsToggle.click()", profile_logic)
        self.assertNotIn("closePanel()", profile_logic)
        self.assertEqual(script.count("btnIris.addEventListener('click'"), 1)
        self.assertIn("body.modo-dev.perfil-iris .inline-ai-bar { display: none; }", style)
        self.assertIn("body.modo-dev.perfil-ares .inline-ai-bar { display: flex; }", style)

    def test_developer_activity_bar_uses_real_feature_panels(self):
        chrome = (ROOT / "static/vscode-chrome.js").read_text(encoding="utf-8")
        navigation = (ROOT / "static/workspace-navigation.js").read_text(encoding="utf-8")
        extensions = (ROOT / "static/extensions-panel.js").read_text(encoding="utf-8")
        self.assertEqual(self.html.count('id="toggleExtensiones"'), 1)
        self.assertEqual(self.html.count('id="toggleTesting"'), 1)
        self.assertEqual(self.html.count('id="toggleTerminalWatcher"'), 1)
        self.assertIn("navigation.open('search')", chrome)
        self.assertIn("runActiveFile", chrome)
        self.assertIn("markSearchActivity", navigation)
        self.assertIn("DECLARATIVE EXTENSIONS", extensions)
        self.assertNotIn("panel de ejemplo", chrome)

    def test_inline_ares_reuses_diff_editor_without_disposing_shared_ui_services(self):
        show_logic = self.inline_ai_source[
            self.inline_ai_source.index("function showDiff("):
            self.inline_ai_source.index("function closeDiff()")
        ]
        close_logic = self.inline_ai_source[
            self.inline_ai_source.index("function closeDiff()"):
            self.inline_ai_source.index("function renderWarnings(")
        ]
        self.assertIn("if (!diffEditor)", show_logic)
        self.assertIn("diffEditor.setModel({ original: originalModel, modified: modifiedModel })", show_logic)
        self.assertLess(show_logic.index("diffEditor.setModel"), show_logic.index("previousOriginal.dispose"))
        self.assertNotIn("diffEditor.dispose()", show_logic + close_logic)
        self.assertNotIn("setModel(null)", close_logic)

    def test_stale_ares_proposal_is_explained_and_closed_after_backend_restart(self):
        self.assertIn(
            "proposal_not_found: 'The proposal no longer exists on the backend. Generate a new one.'",
            self.inline_ai_source,
        )
        self.assertIn("function terminalProposalError(code)", self.inline_ai_source)
        self.assertIn("if (terminalProposalError(error.message))", self.inline_ai_source)
        self.assertIn("proposal = null; approval = null; closeDiff();", self.inline_ai_source)
        self.assertIn("X-Codex-Session-Id", self.inline_ai_source)
        self.assertIn("Internal A.R.E.S. error (reference:", self.inline_ai_source)

    def test_accepted_ares_change_exposes_only_closed_secure_execution_profiles(self):
        for required in (
            'id="inlineAiRunFile"',
            'id="inlineAiRunTests"',
            'id="inlineAiExecution"',
            'id="inlineAiStdout"',
            'id="inlineAiStderr"',
            'id="inlineAiCancelRun"',
        ):
            self.assertIn(required, self.html)
        self.assertIn("root.fetch('/api/ares/tests/runs'", self.inline_ai_source)
        self.assertIn("? 'node_script' : 'python_file'", self.inline_ai_source)
        self.assertIn("runSecure('python_unittest')", self.inline_ai_source)
        self.assertIn("'node_script'", self.inline_ai_source)
        self.assertIn("sandbox_backend:", self.inline_ai_source)
        self.assertIn("exit code:", self.inline_ai_source)
        self.assertIn("duration_seconds", self.inline_ai_source)
        self.assertIn("/api/terminal-watcher/runs/", self.inline_ai_source)
        self.assertNotIn("shell: true", self.inline_ai_source)
        self.assertNotIn("argv:", self.inline_ai_source)

    def test_javascript_execution_waits_for_pending_editor_save(self):
        self.assertIn("function ensureSaved(path)", self.inline_ai_source)
        self.assertIn("if (!info || !info.modified)", self.inline_ai_source)
        self.assertIn("controller.save().then", self.inline_ai_source)
        self.assertLess(
            self.inline_ai_source.index("ensureSaved(activePath)"),
            self.inline_ai_source.index("root.fetch('/api/ares/tests/runs'"),
        )
        self.assertIn("Not run: the current version could not be saved", self.inline_ai_source)
        self.assertIn("return api.save(snapshot).then", self.source)
        self.assertIn("return { ok: false", self.source)
        self.assertIn("geram:workspace-state", self.source)
        self.assertIn("root.addEventListener('geram:workspace-state'", self.inline_ai_source)

    def test_local_intellisense_and_problems_panel_use_monaco_services(self):
        problems = (ROOT / "static/problems.js").read_text(encoding="utf-8")
        for extension in (".jsx", ".ts", ".tsx"):
            self.assertIn("'" + extension + "'", self.monaco_source)
        self.assertIn("checkJs: true", self.monaco_source)
        self.assertIn("noSemanticValidation: false", self.monaco_source)
        self.assertIn("enableSchemaRequest: false", self.monaco_source)
        self.assertIn("onDidChangeMarkers", self.monaco_source)
        self.assertIn("getModelMarkers", self.monaco_source)
        self.assertIn("geram:problems", self.monaco_source)
        self.assertIn("controller.navigate(problem.path", problems)
        self.assertNotIn("innerHTML", problems)
        self.assertNotRegex(problems, r"https?://")
        for required in (
            'id="workspaceProblems"', 'id="workspaceProblemsToggle"',
            'id="workspaceProblemsCount"', 'id="workspaceProblemsList"',
            '<script src="problems.js"></script>',
        ):
            self.assertIn(required, self.html)


if __name__ == "__main__":
    unittest.main()
