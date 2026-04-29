from skyfield.api import load, wgs84
from datetime import datetime, timezone

# 1. Time
ts = load.timescale()
t = ts.now()

# 2. Load Starlink TLEs from CelesTrak
starlink_url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle"
satellites = load.tle_file(starlink_url)

sat = satellites[0]
print(f"Loaded satellite: {sat.name}")

# 3. Define ground station
ground_station = wgs84.latlon(
    latitude_degrees=43.65107,
    longitude_degrees=-79.347015,
    elevation_m=76
)

# 4. Satellite relative to ground station
difference = sat - ground_station
topocentric = difference.at(t)

alt, az, distance = topocentric.altaz()

print(f"\nTime: {datetime.now(timezone.utc)}")
print(f"Elevation angle: {alt.degrees:.2f} degrees")
print(f"Azimuth: {az.degrees:.2f} degrees")
print(f"Distance: {distance.km:.2f} km")

if alt.degrees > 0:
    print("Satellite is VISIBLE from ground station")
else:
    print("Satellite is NOT visible")