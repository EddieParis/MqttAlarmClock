from si4703 import SI4703
from machine import I2C, Pin


i2c = I2C(1, scl=Pin(15), sda=Pin(14), freq=100000)
reset_pin = Pin(16, Pin.OUT)
irq_pin = Pin(17, Pin.IN, Pin.PULL_UP)
radio = SI4703(i2c, reset_pin)

def tuned_handler(frequency):
    print("Tuned to frequency: {:.1f} MHz".format(frequency))
    radio.enable_rds(True)  # Enable RDS when tuned

def basic_tuning_handler(text):
    print("RDS Basic Tuning Text: {}".format(text))

radio.power_cristal(True)
radio.enable(True)
radio.set_tuned_irq(tuned_handler)
radio.set_basic_tuning_handler(basic_tuning_handler)
radio.set_frequency(98.2)  # Set frequency to 98.2 MHz
radio.set_volume(1)       # Set volume to lowest level
radio.mute(False)         # Unmute the audio