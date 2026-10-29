import pytest

from bfme_wizard.vulkan import Device, choose

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
    found = [Device("llvmpipe", CPU, (1, 4)), Device("Intel(R) UHD Graphics", INTEGRATED, (1, 4)),
             Device("Quadro RTX 3000", DISCRETE, (1, 4))]
    assert choose(found) == ("vulkan", "Vulkan 1.4 on Quadro RTX 3000")


def test_one_new_enough_card_is_enough():
    found = [Device("Old GPU", DISCRETE, (1, 2)), Device("Intel(R) UHD Graphics", INTEGRATED, (1, 3))]
    assert choose(found) == ("vulkan", "Vulkan 1.3 on Intel(R) UHD Graphics")
