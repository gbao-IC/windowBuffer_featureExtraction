"""Local packaging/Tcl-control tests only. These do NOT emulate FPGA synthesis."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("synthesis_runner", ROOT / "tools/run_ecg_synthesis.py")
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


class PackagingTests(unittest.TestCase):
    def test_reviewed_model(self):
        flow.validate_model((ROOT / flow.MODEL).read_bytes())

    def test_truncated_model_rejected(self):
        with self.assertRaisesRegex(ValueError, "164"):
            flow.validate_model(b"00000000\n" * 163)

    def test_wrong_word_width_rejected(self):
        with self.assertRaisesRegex(ValueError, "164"):
            flow.validate_model(b"0000\n" * 164)

    def test_corrupt_model_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            flow.validate_model(b"00000000\n" * 164)

    def test_explicit_missing_vivado_does_not_fall_back(self):
        tool, candidates = flow.find_vivado(ROOT / "build/nonexistent_tool/vivado.bat")
        self.assertIsNone(tool)
        self.assertEqual(len(candidates), 1)

    def test_missing_timing_is_not_zero_slack(self):
        with self.assertRaises(ValueError):
            flow.parse_timing_summary("Synthesis has not run")

    def test_full_summary_preserves_negative_slack_and_endpoint_counts(self):
        # Synthetic parser fixture, never included as an FPGA measurement.
        text = "WNS(ns) TNS(ns) endpoints WHS(ns) endpoints WPWS(ns) endpoints\n" \
               "-----\n-1.200 -4.500 3 200 -0.020 -0.040 2 200 5.000 0.000 0 20\n"
        got = flow.parse_timing_summary(text)
        self.assertEqual(got["wns_ns"], -1.2)
        self.assertEqual(got["tns_ns"], -4.5)
        self.assertEqual(got["setup_failing_endpoints"], 3)
        self.assertEqual(got["hold_failing_endpoints"], 2)


class TclTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter
            cls.tkinter = tkinter
            cls.tcl = tkinter.Tcl()
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Tcl interpreter NOT RUN: {exc}")

    def test_tcl_and_xdc_structurally_complete(self):
        for path in (ROOT / "synthesis/ecg").iterdir():
            self.assertEqual(int(self.tcl.call("info", "complete", path.read_text())), 1, path.name)

    def test_xdc_applies_clock_and_both_io_bounds_without_exceptions(self):
        # Tcl syntax/argument capture with explicit stubs. No Vivado API or
        # port matching validation is claimed. Real design queries remain NOT RUN.
        tcl = self.tkinter.Tcl()
        tcl.eval("""
            set calls {}
            proc get_ports {args} {return PORTS}
            proc get_clocks {args} {return CLOCK}
            foreach cmd {create_clock set_clock_uncertainty set_clock_transition
                         set_input_delay set_input_transition set_output_delay set_property} {
                proc $cmd {args} {lappend ::calls [linsert $args 0 [lindex [info level 0] 0]]}
            }
        """)
        tcl.call("source", (ROOT / "synthesis/ecg/ecg_mlp_ooc.xdc").as_posix())
        calls = [tuple(map(str, row)) for row in tcl.getvar("calls")]
        self.assertIn(("create_clock", "-name", "ecg_clk", "-period", "20.000",
                       "-waveform", "0.000 10.000", "PORTS"), calls)
        for cmd in ("set_input_delay", "set_output_delay"):
            self.assertIn((cmd, "-clock", "ecg_clk", "-max", "5.000", "PORTS"), calls)
            self.assertIn((cmd, "-clock", "ecg_clk", "-min", "0.000", "PORTS"), calls)
        self.assertFalse(any(c[0] in {"set_false_path", "set_multicycle_path"} for c in calls))

    def test_tcl_rejects_invalid_mode_before_tool_commands(self):
        tcl = self.tkinter.Tcl()
        tcl.eval('proc exit {code} {error "TEST_EXIT_$code"}; proc puts {args} {}')
        tcl.setvar("argv", tcl.call("list", "unused", "invalid"))
        with self.assertRaisesRegex(self.tkinter.TclError, "TEST_EXIT_1"):
            tcl.call("source", (ROOT / "synthesis/ecg/run_vivado.tcl").as_posix())
        self.assertEqual(tcl.getvar("message"), "Mode must be synth or route")

    def test_tcl_refuses_existing_output(self):
        tcl = self.tkinter.Tcl()
        tcl.eval('proc exit {code} {error "TEST_EXIT_$code"}; proc puts {args} {}')
        tcl.setvar("argv", tcl.call("list", ROOT.as_posix(), "synth"))
        with self.assertRaisesRegex(self.tkinter.TclError, "TEST_EXIT_1"):
            tcl.call("source", (ROOT / "synthesis/ecg/run_vivado.tcl").as_posix())
        self.assertIn("Refusing to overwrite existing output", tcl.getvar("message"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
