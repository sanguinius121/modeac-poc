"""Reception provider interface documentation."""


class ReceptionProvider:
    def evaluate(self, receiver, target_lat, target_lon, target_altitude_m):
        """Return (eligible, explanation metadata) for one horizontal point."""
        raise NotImplementedError

    def prepare(self, receiver, points, target_altitude_m):
        return [self.evaluate(receiver,lat,lon,target_altitude_m) for lat,lon in points]
