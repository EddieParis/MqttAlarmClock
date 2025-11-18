from si4703 import SI4703
from machine import I2C, Pin

i2c = I2C(1, scl=Pin(15), sda=Pin(14), freq=100000)
reset_pin = Pin(16, Pin.OUT)
irq_pin = Pin(17, Pin.IN, Pin.PULL_UP)
radio = SI4703(i2c, reset_pin)

radio.power_cristal(True)
radio.mute(False)
radio.enable(True)

radio.set_frequency(98.2)  # Set frequency to 98.2 MHz