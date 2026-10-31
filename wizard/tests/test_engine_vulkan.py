import subprocess

import pytest

from bfme_wizard.engine import graphics
from bfme_wizard.engine.vulkan import Device, choose

DISCRETE, INTEGRATED, CPU = 2, 1, 4


def test_no_vulkan_loader_means_opengl():
    assert choose(None) == ("opengl", "Vulkan is not available")


@pytest.mark.parametrize("found", [[], [Device("llvmpipe (LLVM 21.1.8, 256 bits)", CPU, (1, 4))]])
def test_only_a_software_renderer_means_opengl(found):
    assert choose(found) == ("opengl", "no graphics card with Vulkan was found")


def test_a_card_below_vulkan_1_3_means_opengl():
    backend, why = choose([Device("Intel(R) HD Graphics 4600", INTEGRATED, (1, 2))])
    assert backend == "opengl"
    assert why == "Vulkan 1.2 on Intel(R) HD Graphics 4600, but Vulkan 1.3 or newer is needed"


def test_a_card_with_vulkan_1_3_means_vulkan():
    assert choose([Device("AMD Radeon RX 580", DISCRETE, (1, 3))]) == ("vulkan", "Vulkan 1.3 on AMD Radeon RX 580")


def test_the_best_card_is_named_and_a_dedicated_one_wins_a_tie():
    found = [
        Device("llvmpipe", CPU, (1, 4)),
        Device("Intel(R) UHD Graphics", INTEGRATED, (1, 4)),
        Device("Quadro RTX 3000", DISCRETE, (1, 4)),
    ]
    assert choose(found) == ("vulkan", "Vulkan 1.4 on Quadro RTX 3000")


def test_one_new_enough_card_is_enough():
    found = [Device("Old GPU", DISCRETE, (1, 2)), Device("Intel(R) UHD Graphics", INTEGRATED, (1, 3))]
    assert choose(found) == ("vulkan", "Vulkan 1.3 on Intel(R) UHD Graphics")


# The probe, run as the setup runs it


def test_the_probe_runs_as_a_child_process_and_answers():
    backend, why = graphics.probe()

    assert backend in ("vulkan", "opengl", "unknown")
    assert why


@pytest.mark.parametrize(
    "output,expected",
    [
        ("vulkan Vulkan 1.4 on Test GPU\n", ("vulkan", "Vulkan 1.4 on Test GPU")),
        ("opengl no graphics card with Vulkan was found\n", ("opengl", "no graphics card with Vulkan was found")),
        ("unknown could not check Vulkan (boom)\n", ("unknown", "could not check Vulkan (boom)")),
        ("", ("unknown", "could not check Vulkan")),
        ("Segmentation fault\n", ("unknown", "could not check Vulkan")),
    ],
)
def test_the_probes_answer_is_read(monkeypatch, output, expected):
    monkeypatch.setattr(graphics.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=output))

    assert graphics.probe() == expected


def test_a_hung_probe_is_unknown(monkeypatch):
    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(args, graphics.PROBE_TIMEOUT_SEC)

    monkeypatch.setattr(graphics.subprocess, "run", hang)

    assert graphics.probe() == ("unknown", "could not check Vulkan")
