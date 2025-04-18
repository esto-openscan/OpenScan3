from app.controllers.settings import Settings
from app.models.light import Light, LightConfig

from . import gpio
from .interfaces import SwitchableHardware, create_controller_registry

class LightController(SwitchableHardware):
    def __init__(self, light: Light):
        self.model = light
        self.settings = Settings(
            light.settings,
            on_change=self._apply_settings_to_hardware
        )
        self._apply_settings_to_hardware()
        self._is_on = False

    def _apply_settings_to_hardware(self):
        # apply to model
        self.model.settings = self.settings

        # apply to hardware
        gpio.initialize_pins(self.settings.pins)

    def get_status(self):
        return {
            "name": self.model.name,
            "is_on": self.is_on(),
            "settings": self.get_config()
        }

    def get_config(self) -> LightConfig:
        return self.settings.model

    def is_on(self) -> bool:
        return self._is_on

    def turn_on(self):
        for pin in self.settings.pins:
            gpio.set_pin(pin, True)
        self._is_on = True

    def turn_off(self):
        for pin in self.settings.pins:
            gpio.set_pin(pin, False)
        self._is_on = False


create_light_controller, get_light_controller, remove_light_controller, _light_registry = create_controller_registry(LightController)


def get_all_light_controllers():
    """Get all currently registered light controllers"""
    return _light_registry.copy()
