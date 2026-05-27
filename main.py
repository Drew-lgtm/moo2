import pygame

from ecs.save_manager import init_save_slots
from ecs.game import Game
from ecs.scenes import (
    MainMenuScene,
    GalaxyScene,
    SystemViewScene,
    ColonyScene,
    BuildScene,
    ResearchScene,
    DiplomacyScene,
    CouncilScene,
    CombatReportScene,
    IdleColoniesScene,
    GameOverScene,
    SaveSlotScene,
    PauseScene,
    EmpireSetupScene,
    EspionageScene,
    ColoniesScene,
    PlanetsScene,
    LeadersScene,
    RacesScene,
    InfoScene,
)


def main():
    pygame.init()
    init_save_slots()

    game = Game(screen_width=1200, screen_height=800, num_stars=40)
    game.scenes.register("main_menu", MainMenuScene(game))
    game.scenes.register("empire_setup", EmpireSetupScene(game))
    game.scenes.register("espionage", EspionageScene(game))
    game.scenes.register("galaxy", GalaxyScene(game))
    game.scenes.register("system", SystemViewScene(game))
    game.scenes.register("colony", ColonyScene(game))
    game.scenes.register("build", BuildScene(game))
    game.scenes.register("research", ResearchScene(game))
    game.scenes.register("diplomacy", DiplomacyScene(game))
    game.scenes.register("council", CouncilScene(game))
    game.scenes.register("combat_report", CombatReportScene(game))
    game.scenes.register("idle_colonies", IdleColoniesScene(game))
    game.scenes.register("game_over", GameOverScene(game))
    game.scenes.register("saves", SaveSlotScene(game))
    game.scenes.register("pause", PauseScene(game))
    game.scenes.register("colonies", ColoniesScene(game))
    game.scenes.register("planets", PlanetsScene(game))
    game.scenes.register("leaders", LeadersScene(game))
    game.scenes.register("races", RacesScene(game))
    game.scenes.register("info", InfoScene(game))

    game.run("main_menu")


if __name__ == "__main__":
    main()
