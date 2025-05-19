#!/bin/bash

# Define the base directory
BASE_DIR="assets"

# Create the main directories
mkdir -p "$BASE_DIR/backgrounds" "$BASE_DIR/stars" "$BASE_DIR/races" "$BASE_DIR/ships" "$BASE_DIR/fonts" "$BASE_DIR/sounds"

# Create placeholder images for races
declare -A races=(
  ["Alkari"]="alkari.png"
  ["Bulrathi"]="bulrathi.png"
  ["Cynoid"]="cynoid.png"
  ["Eoladi"]="eoladi.png"
  ["Imsaeis"]="imsaeis.png"
  ["Klackon"]="klackon.png"
  ["Meklar"]="meklar.png"
  ["Mrrshan"]="mrrshan.png"
  ["Nommo"]="nommo.png"
  ["Psilon"]="psilon.png"
  ["Raas"]="raas.png"
  ["Sakkra"]="sakkra.png"
  ["Silicoid"]="silicoid.png"
  ["Trilarian"]="trilarian.png"
  ["Humans"]="humans.png"
)

for race in "${!races[@]}"; do
  touch "$BASE_DIR/races/${races[$race]}"
done

# Create placeholder images for ships
declare -A ships=(
  ["Frigate"]="frigate.png"
  ["Cruiser"]="cruiser.png"
  ["Dreadnought"]="dreadnought.png"
  ["BattleShip"]="battleship.png"
  ["Carrier"]="carrier.png"
)

for ship in "${!ships[@]}"; do
  touch "$BASE_DIR/ships/${ships[$ship]}"
done

# Create placeholder files for fonts and sounds
touch "$BASE_DIR/fonts/main.ttf"
touch "$BASE_DIR/sounds/click.wav" "$BASE_DIR/sounds/music.ogg"

echo "Master of Orion asset structure created successfully."

