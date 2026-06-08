import json

class Timeline:
    def __init__(self):
        self.events = []

    def add(self, event):
        self.events.append(event)

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.events, f, indent=2)

