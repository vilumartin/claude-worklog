on pad(n)
  if n < 10 then return "0" & n
  return "" & n
end pad
on iso(d)
  return (year of d as string) & "-" & pad(month of d as integer) & "-" & pad(day of d) & "T" & pad(hours of d) & ":" & pad(minutes of d) & ":" & pad(seconds of d)
end iso
on run argv
  set daysBack to (item 1 of argv) as integer
  set cutoff to (current date) - (daysBack * days)
  set out to ""
  tell application "Mail"
    repeat with acc in accounts
      try
        set mb to mailbox "INBOX" of acc
        set n to count of messages of mb
        set i to 1
        repeat while i ≤ n and i ≤ 600
          set m to message i of mb
          set d to date received of m
          if d < cutoff then exit repeat
          if (sender of m) contains "fathom.video" and (subject of m) starts with "Recap" then
            set c to content of m
            if (length of c) > 400 then set c to text 1 thru 400 of c
            set AppleScript's text item delimiters to {linefeed, return}
            set parts to text items of c
            set AppleScript's text item delimiters to " "
            set c to parts as string
            set AppleScript's text item delimiters to ""
            set out to out & my iso(d) & "|" & (subject of m) & "|" & c & linefeed
          end if
          set i to i + 1
        end repeat
      end try
    end repeat
  end tell
  return out
end run
