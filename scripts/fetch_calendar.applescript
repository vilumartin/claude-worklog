on pad(n)
  if n < 10 then return "0" & n
  return "" & n
end pad
on iso(d)
  return (year of d as string) & "-" & pad(month of d as integer) & "-" & pad(day of d) & "T" & pad(hours of d) & ":" & pad(minutes of d) & ":00"
end iso
on run argv
  set daysBack to (item 1 of argv) as integer
  set calNames to items 2 thru -1 of argv
  set d1 to (current date) - (daysBack * days)
  set d2 to (current date) + (1 * days)
  set out to ""
  tell application "Calendar"
    repeat with cn in calNames
      try
        set cal to first calendar whose name is (cn as string)
        set calName to (cn as string)
        set evs to (every event of cal whose start date ≥ d1 and start date ≤ d2)
        repeat with e in evs
          set att to ""
          try
            repeat with a in attendees of e
              set att to att & (email of a) & ":" & (participation status of a as string) & ";"
            end repeat
          end try
          set rec to "0"
          try
            if (recurrence of e) is not missing value then set rec to "1"
          end try
          set tx to ""
          try
            set tx to (summary of e)
          end try
          set stTxt to ""
          try
            set stTxt to (status of e) as string
          end try
          set adTxt to "false"
          try
            set adTxt to (allday event of e) as string
          end try
          set out to out & calName & "|" & (uid of e) & "|" & my iso(start date of e) & "|" & my iso(end date of e) & "|" & adTxt & "|" & stTxt & "|" & rec & "|" & att & "|" & tx & linefeed
        end repeat
      on error m
        set out to out & "ERR|" & (cn as string) & "|" & m & linefeed
      end try
    end repeat
  end tell
  return out
end run
