#!/bin/bash
# Gets used RAM in GB
used=$(free -h | awk '/Mem:/ {print $3}' | sed 's/i//g')
echo "{\"text\": \" $used\"}"
