import os
import signal
import subprocess
import sys
import time
task = sys.argv[1] if len(sys.argv) == 2 else ""
if task == "stdout": print("terminal watcher stdout")
elif task == "stderr": print("terminal watcher stderr", file=sys.stderr)
elif task == "failure": raise SystemExit(7)
elif task in {"timeout", "cancelable"}: print("running", flush=True); time.sleep(60)
elif task == "large_output": print("x" * 200000)
elif task == "environment_probe":
    names = ("OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    print("present=" + str(sum(bool(os.environ.get(name)) for name in names)))
elif task == "stdin_probe": print("eof=" + str(sys.stdin.read(1) == ""))
elif task == "secret_output_probe": print("synthetic-secret-marker")
elif task in {"child_tree", "child_tree_resistant"}:
    if task == "child_tree_resistant": signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print("child-started", flush=True); time.sleep(60)
elif task == "fs_read_allowed": print(open("allowed.txt", encoding="utf-8").read())
elif task == "fs_read_external": print(open("../external/external.txt", encoding="utf-8").read())
elif task == "fs_write_allowed": open("allowed-write.txt", "w", encoding="utf-8").write("synthetic-write")
elif task == "fs_write_external": open("../external/external-write-target", "w", encoding="utf-8").write("synthetic-write")
else: raise SystemExit(2)
