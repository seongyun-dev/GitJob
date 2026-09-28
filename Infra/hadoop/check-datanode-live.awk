BEGIN {
  in_live = 0
  matching_name = 0
  found = 0
}

/^Live datanodes \([0-9]+\):/ {
  in_live = 1
  matching_name = 0
  next
}

/^Dead datanodes \([0-9]+\):/ {
  in_live = 0
  matching_name = 0
  next
}

in_live && /^Name:[[:space:]]+/ {
  matching_name = ($2 ~ (":" expected_port "$"))
  next
}

in_live && matching_name && /^Hostname:[[:space:]]+/ && $2 == expected_hostname {
  found = 1
}

END {
  exit(found ? 0 : 1)
}
