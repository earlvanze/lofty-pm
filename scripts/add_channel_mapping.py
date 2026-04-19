#!/usr/bin/env python3
"""
Add Discord channel mapping to property_update_map.json

Usage:
  python3 add_channel_mapping.py --list
  python3 add_channel_mapping.py --channel CHANNEL_ID --property "917 Pawnee"

This enforces that Atlas Relay updates for a property can only come from
the designated Discord channel for that property.
"""
import argparse, json, sys
from pathlib import Path

MAP_FILE = Path(__file__).resolve().parent.parent / 'config' / 'property_update_map.json'

def load_map():
    data = json.loads(MAP_FILE.read_text())
    return data.get('properties', data) if isinstance(data, dict) else data

def save_map(props):
    MAP_FILE.write_text(json.dumps({'properties': props}, indent=2) + '\n')

def find_property(props, key):
    keyl = key.lower()
    for p in props:
        if key == p.get('lofty_property_id') or key == p.get('slug'):
            return p
        if keyl in (p.get('property_name', '').lower(), 
                    p.get('full_address', '').lower(),
                    p.get('assetUnit', '').lower()):
            return p
    return None

def main():
    ap = argparse.ArgumentParser(description='Add Discord channel mapping to property_update_map.json')
    ap.add_argument('--channel', help='Discord channel ID (numeric)')
    ap.add_argument('--property', help='Property name, ID, or slug')
    ap.add_argument('--list', action='store_true', help='List all properties and their channel mappings')
    ap.add_argument('--remove', action='store_true', help='Remove channel mapping')
    args = ap.parse_args()
    
    props = load_map()
    
    if args.list:
        print(f"{'#':<3} {'Property':<45} {'Channel':<25}")
        print("-" * 75)
        for i, p in enumerate(props):
            ch = p.get('discord_channel_id', 'NOT_SET')
            print(f"{i+1:<3} {p['property_name'][:45]:<45} {ch:<25}")
        print(f"\nTotal: {len(props)} properties")
        return
    
    if not args.channel and not args.property:
        ap.error("--channel and --property are required (unless using --list)")
    
    prop = find_property(props, args.property)
    if not prop:
        print(f"Property not found: {args.property}")
        print("Use --list to see available properties")
        sys.exit(1)
    
    if args.remove:
        prop.pop('discord_channel_id', None)
    else:
        prop['discord_channel_id'] = args.channel
    
    save_map(props)
    print(f"Updated: {prop['property_name']}")
    print(f"  Channel: {prop.get('discord_channel_id', 'removed')}")

if __name__ == '__main__':
    main()
