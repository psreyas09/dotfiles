#!/bin/bash
# Gets used RAM in GiB and formats it
used=$(free -g | awk '/Mem:/ {print $3}')
echo "{\"text\": \" ${used}G\", \"tooltip\": \"Actual RAM usage from system\"}"
