from si4703 import SI4703
from machine import I2C, Pin
import time



sda = Pin(4, Pin.OUT)
scl = Pin(15, Pin.OUT)

sen_pin = Pin(18, Pin.OUT)
reset_pin = Pin(19, Pin.OUT)
irq_pin = Pin(21, Pin.IN, Pin.PULL_UP)


sda.value(0)
sen_pin.value(1)    # Enable I2C mode

# Reset the chip
reset_pin.value(0)
time.sleep(0.2)
reset_pin.value(1)
time.sleep(0.1)

sda.value(1)
i2c = I2C(1, scl=scl, sda=sda, freq=100000)

radio = SI4703(i2c, reset_pin, sen_pin, irq_pin)

def tuned_handler(frequency, rssi):
    print("Tuned to frequency: {:.1f} MHz, RSSI: {}".format(frequency, rssi))
    radio.enable_rds(True)  # Enable RDS when tuned

def basic_tuning_handler(text):
    print("RDS Basic Tuning Text: {}".format(text))

radio.power_cristal(True)
radio.enable(True)
radio.set_tuned_irq(tuned_handler)
radio.set_basic_tuning_handler(basic_tuning_handler)
radio.set_frequency(98.2)   # Set frequency to 98.2 MHz
radio.set_volume(1)         # Set volume to lowest level
radio.mute(False)           # Unmute the audio

while True:
    time.sleep(1)
