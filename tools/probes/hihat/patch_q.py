_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0, str(_ROOT / "model"))
def pytest_configure(config):
    import drums_fx as dx
    dx.CY_HI_Q = 4.0
