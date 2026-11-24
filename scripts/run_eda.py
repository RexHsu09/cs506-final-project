"""Execute the EDA with this Python interpreter and a temporary local kernel specification."""
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
locations = {"TMPDIR": ROOT/".cache/tmp", "MPLCONFIGDIR": ROOT/".cache/matplotlib",
    "IPYTHONDIR": ROOT/".cache/ipython", "JUPYTER_RUNTIME_DIR": ROOT/".cache/runtime",
    "JUPYTER_CONFIG_DIR": ROOT/".cache/jupyter_config", "JUPYTER_PATH": ROOT/".cache/jupyter"}
for key,path in locations.items():
    path.mkdir(parents=True,exist_ok=True)
    os.environ[key] = str(path)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
spec = ROOT/".cache/jupyter/kernels/cs506-roads"
spec.mkdir(parents=True,exist_ok=True)
(spec/"kernel.json").write_text(json.dumps({"argv":[sys.executable,"-m","ipykernel_launcher","-f","{connection_file}"],
    "display_name":"CS506 road EDA", "language":"python"}))

import nbformat
from nbclient import NotebookClient
path = ROOT/"notebooks/02_eda.ipynb"
nb = nbformat.read(path,as_version=4)
client = NotebookClient(nb, timeout=240, kernel_name="cs506-roads", resources={"metadata":{"path":str(ROOT)}})
try:
    client.execute()
finally:
    nbformat.write(nb,path)
errors = [output for cell in nb.cells for output in cell.get("outputs",[]) if output.output_type=="error"]
assert not errors, errors
print(json.dumps({"executed_cells":sum(c.cell_type=="code" for c in nb.cells),
                  "error_outputs":len(errors),"summary":json.loads((ROOT/"reports/analysis_summary.json").read_text())},indent=2))
