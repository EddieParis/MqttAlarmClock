from collections import deque

class Event:
    ROT_CW = 0
    ROT_CCW = 1
    ROT_PUSH = 2
    ROT_REL = 3
    KO_PUSH = 4
    KO_REL = 5
    TUNED = 6
    RDS_Basic_Tuning = 7
    RDS_Radio_Text = 8
    MODE_ENTER = 9

    def __init__(self, event_type):
        self.type = event_type

class EventRotCwEvent(Event):
    def __init__(self, fast=False):
        super().__init__(Event.ROT_CW)
        self.fast = fast

class EventRotCcwEvent(Event):
    def __init__(self, fast=False):
        super().__init__(Event.ROT_CCW)
        self.fast = fast

class RadioTunedEvent(Event):
    def __init__(self, frequency, rssi):
        super().__init__(Event.TUNED)
        self.frequency = frequency
        self.rssi = rssi

class BasicTuningEvent(Event):
    def __init__(self, text):
        super().__init__(Event.RDS_Basic_Tuning)
        self.text = text

class RadioTextEvent(Event):
    def __init__(self, text):
        super().__init__(Event.RDS_Radio_Text)
        self.text = text

class EventsQueue:
    def __init__(self, event_flag):
        self.queue = deque((), 10)
        self.event_flag = event_flag

    def push(self, event):
        self.queue.append(event)
        self.event_flag.set()

    def pop(self):
        if len(self.queue) == 0:
            return None
        return self.queue.popleft()
