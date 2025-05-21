import pygame

class Menu:
    def __init__(self, screen, options, title=""):
        self.screen = screen
        self.options = options
        self.selected_index = 0
        self.title = title
        self.font = pygame.font.SysFont("Arial", 24)


    def draw(self):
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))

        center_x = self.screen.get_width() // 2
        center_y = self.screen.get_height() // 2

        if self.title:
            title_surface = self.font.render(self.title, True, (255, 255, 255))
            overlay.blit(title_surface, title_surface.get_rect(center=(center_x, center_y - 100)))

        for i, text in enumerate(self.options):
            color = (255, 255, 0) if i == self.selected_index else (255, 255, 255)
            rendered = self.font.render(text, True, color)
            rect = rendered.get_rect(center=(center_x, center_y + i * 40))
            overlay.blit(rendered, rect)

        self.screen.blit(overlay, (0, 0))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_UP:
                self.selected_index = (self.selected_index - 1) % len(self.options)
            elif event.key == pygame.K_DOWN:
                self.selected_index = (self.selected_index + 1) % len(self.options)
            elif event.key == pygame.K_RETURN:
                return self.options[self.selected_index]
        return None
