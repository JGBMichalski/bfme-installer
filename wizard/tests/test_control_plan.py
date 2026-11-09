"""control.plan and control.steps: what the player chose, the jobs it takes, and the steps of each."""

from bfme_wizard.control.plan import Plan
from bfme_wizard.control.steps import STEPS


def test_a_choice_is_kept_in_install_order_and_unknown_programs_are_left_out():
    plan = Plan()

    assert plan.choose(["aotr", "teleport", "aio-launcher"]) == ("aio-launcher", "aotr")
    assert plan.same_choice(["aotr", "aio-launcher"])
    assert not plan.same_choice(["aotr"])


def test_a_plan_has_the_game_environment_first_when_it_is_not_ready():
    plan = Plan()

    assert plan.begin(["aotr"], environment_ready=False, from_home=False)
    assert plan.jobs == ["environment", "aotr"]
    assert plan.step_ids == [
        "doctor",
        "runner",
        "prefix",
        "aotr-download",
        "aotr-unpack",
        "aotr-install",
        "aotr-settings",
    ]
    assert set(plan.steps.values()) == {"pending"}


def test_nothing_chosen_is_no_plan():
    assert not Plan().begin([], environment_ready=False, from_home=False)


def test_a_finished_job_leaves_the_next_one_and_counts_its_steps():
    plan = Plan()
    plan.begin(["aio-launcher", "aotr"], environment_ready=True, from_home=False)
    plan.steps["aio-launcher"] = "done"
    plan.finish_job("aio-launcher")  # the steps it did not report are done too

    assert plan.first_unfinished_job() == "aotr"
    assert plan.done_count == 3
    assert plan.step_number(None) == 4
    assert plan.step_number("aotr-install") == 6


def test_the_catalog_finds_a_steps_words():
    assert STEPS.title_of("aotr-unpack") == "Unpack the download"
    assert STEPS.title_of("teleport") == "teleport"
    assert STEPS.description_of("teleport") == ""


# Every list of programs in the wizard comes from engine/programs.


def test_the_wizard_knows_the_programs_in_the_order_it_shows_them():
    from bfme_wizard.control.apps import AppLauncher
    from bfme_wizard.control.steps import STEPS

    assert STEPS.programs == ["aio-launcher", "arena", "aotr"]
    assert STEPS.choices == ["aio-launcher", "aotr"]  # the start page's choices: the Arena comes with the AIO Launcher
    assert STEPS.tools == ["workshop", "mission-control"]
    assert list(AppLauncher(lambda *_a: 0, lambda: None).state) == [*STEPS.programs, *STEPS.tools]

    for key in ("environment", "aio-launcher", "aotr", *STEPS.tools):
        assert key in STEPS.by_job

    assert "arena" not in STEPS.by_job  # the AIO Launcher's job installs it
