;;; Render live clock dashboard text as JSON (batch) -*- lexical-binding: t; -*-

(require 'calendar)
(require 'cl-lib)
(require 'json)
(require 'org)
(require 'org-id)

;; Defined by the user's Emacs init file, which is loaded before this script.
(declare-function my/org-clock-suspects "ext:init-org" (files))
(declare-function my/org--collect-ts-pos "ext:init-org" (s))
(declare-function my/org--ts->sec "ext:init-org" (ts))
(declare-function my/org-clocklog-rows "ext:init-org" (&optional date-str files))
(declare-function my/org-clocklog--fmt-hhmm "ext:init-org" (sec))
(declare-function my/org-clocklog--fmt-dur "ext:init-org" (mins))

;; The user's init-org.el resolves dangling clocks whenever an Org buffer opens.
;; Dashboard reads must never mutate source Org files.
(when (boundp 'my/org-auto-resolve-dangling-clocks)
  (setq my/org-auto-resolve-dangling-clocks nil))

;; Emacs visits only *.org files in Org mode by default.  Archives written by
;; Org carry a mode line, but the scans below must not depend on it.
(add-to-list 'auto-mode-alist '("\\.org_archive\\'" . org-mode))

(defconst org-timeviz-dashboard--json-prefix "ORG_TIMEVIZ_CLOCK_DASHBOARD_JSON:")

(defun org-timeviz-dashboard--require-helper (symbol)
  "Fail clearly when the user's init file does not define SYMBOL."
  (unless (fboundp symbol)
    (error "Clock dashboard requires %S in the configured Emacs init file" symbol)))

(defun org-timeviz-dashboard--link-description (value)
  "Return the visible description from Org link VALUE, when present."
  (org-link-display-format (format "%s" value)))

(defun org-timeviz-dashboard--cell-string (value)
  "Convert VALUE to a single-line table cell string."
  (replace-regexp-in-string "[\n\r]+" " " (format "%s" (or value ""))))

(defun org-timeviz-dashboard--column-widths (headers rows)
  "Return display widths for HEADERS and ROWS."
  (let ((widths (mapcar (lambda (cell)
                          (length (org-timeviz-dashboard--cell-string cell)))
                        headers)))
    (dolist (row rows)
      (cl-loop for cell in row
               for index from 0
               do (setf (nth index widths)
                        (max (nth index widths)
                             (length (org-timeviz-dashboard--cell-string cell))))))
    widths))

(defun org-timeviz-dashboard--render-row (row widths)
  "Render ROW using WIDTHS as an ASCII table row."
  (concat
   "| "
   (mapconcat
    #'identity
    (cl-mapcar
     (lambda (cell width)
       (format (format "%%-%ds" width)
               (org-timeviz-dashboard--cell-string cell)))
     row widths)
    " | ")
   " |"))

(defun org-timeviz-dashboard--render-table (headers rows)
  "Render HEADERS and ROWS as a compact plain-text table."
  (let* ((widths (org-timeviz-dashboard--column-widths headers rows))
         (separator
          (concat "|-"
                  (mapconcat (lambda (width) (make-string width ?-)) widths "-+-")
                  "-|")))
    (mapconcat
     #'identity
     (append
      (list (org-timeviz-dashboard--render-row headers widths) separator)
      (mapcar (lambda (row) (org-timeviz-dashboard--render-row row widths)) rows))
     "\n")))

(defun org-timeviz-dashboard--suspect-text (files intervals)
  "Render clock-line issues across FILES and repeated clocks among INTERVALS.
Overlapping intervals are reported separately as structured records."
  (let* ((issue-rows
          (mapcar
           (lambda (row)
             (list (nth 0 row)
                   (org-timeviz-dashboard--link-description (nth 1 row))
                   (nth 2 row)
                   (nth 3 row)
                   (nth 4 row)))
           (my/org-clock-suspects files)))
         (duplicate-rows (org-timeviz-dashboard--duplicate-rows intervals))
         (sections
          (delq nil
                (list
                 (when issue-rows
                   (concat
                    "Clock-line issues:\n"
                    (org-timeviz-dashboard--render-table
                     '("File" "Heading" "Issue" "Clock line" "Details")
                     issue-rows)))
                 (when duplicate-rows
                   (concat
                    "Possible duplicate clocks, each still counted in all totals:\n"
                    (org-timeviz-dashboard--render-table
                     '("Heading" "Interval" "Location" "Duplicate location")
                     duplicate-rows)))))))
    (if sections
        (mapconcat #'identity sections "\n\n")
      "All CLOCK lines look standard.")))

(defun org-timeviz-dashboard--timestamp-identity (timestamp)
  "Return Org TIMESTAMP as a timezone-independent YYYY-MM-DDTHH:MM string."
  (let ((parsed (org-parse-time-string timestamp)))
    (format "%04d-%02d-%02dT%02d:%02d"
            (nth 5 parsed) (nth 4 parsed) (nth 3 parsed)
            (nth 2 parsed) (nth 1 parsed))))

(defun org-timeviz-dashboard--all-intervals (files)
  "Collect closed and open clock intervals from FILES.
Each row is (START END FILE HEADING OPEN LINE ORG-ID START-STAMP END-STAMP).
LINE is the 1-based line number of the CLOCK line itself.  ORG-ID is the
owning heading's own ID property, or nil; it is never created here.
START-STAMP and END-STAMP are the clock's timestamps as written, normalized
by `org-timeviz-dashboard--timestamp-identity'; END-STAMP is nil for open
clocks."
  (let ((rows '())
        (now (float-time (current-time))))
    (dolist (file files)
      (with-current-buffer (find-file-noselect file)
        (save-excursion
          (goto-char (point-min))
          (while (re-search-forward "^ *CLOCK: *\\(.*\\)$" nil t)
            (let* ((payload (match-string 1))
                   ;; Read the line before point moves to the owning heading.
                   (line (line-number-at-pos (match-beginning 0) t))
                   (timestamps (my/org--collect-ts-pos payload)))
              (when (memq (length timestamps) '(1 2))
                (let* ((start (my/org--ts->sec (caar timestamps)))
                       (open (= (length timestamps) 1))
                       (end (if open
                                now
                              (my/org--ts->sec (caadr timestamps)))))
                  (when (< start end)
                    (save-excursion
                      (condition-case nil
                          (progn
                            (org-back-to-heading t)
                            (push
                             (list start
                                   end
                                   (file-name-nondirectory file)
                                   (org-get-heading t t t t)
                                   open
                                   line
                                   (org-id-get)
                                   (org-timeviz-dashboard--timestamp-identity
                                    (caar timestamps))
                                   (unless open
                                     (org-timeviz-dashboard--timestamp-identity
                                      (caadr timestamps))))
                             rows))
                        (error nil)))))))))))
    (cl-sort rows #'< :key #'car)))

(defun org-timeviz-dashboard--interval-label (row)
  "Format interval ROW for the overlap report."
  (format "%s--%s%s"
          (format-time-string "%Y-%m-%d %H:%M" (seconds-to-time (nth 0 row)))
          (format-time-string "%Y-%m-%d %H:%M" (seconds-to-time (nth 1 row)))
          (if (nth 4 row) " (open)" "")))

(defun org-timeviz-dashboard--task-label (row)
  "Format interval ROW's file and heading."
  (format "%s: %s" (nth 2 row) (nth 3 row)))

(defun org-timeviz-dashboard--location-label (row)
  "Format interval ROW's CLOCK line as FILE:LINE."
  (format "%s:%s" (nth 2 row) (nth 5 row)))

(defun org-timeviz-dashboard--duplicate-rows (intervals)
  "Return table rows for closed INTERVALS that repeat another CLOCK line.
Two CLOCK lines with the same timestamps under the same heading text are most
likely one entry recorded twice, for example a task left in an active file
after it was also archived.  Legitimate overlaps of different headings are not
reported.  Each pair lists the smaller file name and line first, so an active
file comes before its archive.  INTERVALS must be sorted by start, as returned
by `org-timeviz-dashboard--all-intervals'."
  (let ((rows '()))
    (cl-loop
     for (row . later) on intervals
     do (cl-loop
         for other in later
         while (= (nth 0 other) (nth 0 row))
         when (and (nth 8 row)
                   (equal (nth 7 other) (nth 7 row))
                   (equal (nth 8 other) (nth 8 row))
                   (equal (nth 3 other) (nth 3 row)))
         do (let ((pair (sort (list row other)
                              (lambda (left right)
                                (org-timeviz-dashboard--key<
                                 (list (nth 2 left) (nth 5 left))
                                 (list (nth 2 right) (nth 5 right)))))))
              (push (list (nth 3 row)
                          (org-timeviz-dashboard--interval-label row)
                          (org-timeviz-dashboard--location-label (nth 0 pair))
                          (org-timeviz-dashboard--location-label (nth 1 pair)))
                    rows))))
    (nreverse rows)))

(defun org-timeviz-dashboard--display-key (row)
  "Return the key ordering interval ROW within a displayed overlap pair.
Shorter task labels sort first; the remaining fields break ties so the
order never depends on which interval the overlap scan found first."
  (let ((label (org-timeviz-dashboard--task-label row)))
    (list (length label) label (nth 0 row) (nth 1 row) (if (nth 4 row) 1 0)
          (nth 5 row))))

(defun org-timeviz-dashboard--key< (left right)
  "Return non-nil when sort key LEFT strictly precedes sort key RIGHT."
  (cl-loop for left-value in left
           for right-value in right
           unless (equal left-value right-value)
           return (if (stringp left-value)
                      (string< left-value right-value)
                    (< left-value right-value))))

(defun org-timeviz-dashboard--display-pair (first second)
  "Return intervals FIRST and SECOND with the shorter task label first."
  (if (org-timeviz-dashboard--key< (org-timeviz-dashboard--display-key second)
                                   (org-timeviz-dashboard--display-key first))
      (list second first)
    (list first second)))

(defun org-timeviz-dashboard--overlap-clock (row)
  "Return interval ROW as a JSON-ready overlap clock record."
  `((task . ,(org-timeviz-dashboard--task-label row))
    (interval . ,(org-timeviz-dashboard--interval-label row))
    (file . ,(nth 2 row))
    (line . ,(nth 5 row))
    (org_id . ,(nth 6 row))
    (start . ,(nth 7 row))
    (end . ,(nth 8 row))))

(defun org-timeviz-dashboard--overlap-records (intervals)
  "Return a JSON-ready vector describing every pair of overlapping INTERVALS.
INTERVALS are rows from `org-timeviz-dashboard--all-intervals'.  Task A is
the interval with the shorter task label."
  (let ((active '())
        (overlaps '()))
    (dolist (row intervals)
      (setq active
            (cl-remove-if
             (lambda (other) (<= (nth 1 other) (nth 0 row)))
             active))
      (dolist (other active)
        (let ((pair (org-timeviz-dashboard--display-pair other row)))
          (push
           `((a . ,(org-timeviz-dashboard--overlap-clock (nth 0 pair)))
             (b . ,(org-timeviz-dashboard--overlap-clock (nth 1 pair))))
           overlaps)))
      (push row active))
    (vconcat (nreverse overlaps))))

(defun org-timeviz-dashboard--clocklog-text (date-str rows)
  "Render chronological clock ROWS for DATE-STR."
  (let ((display-rows '())
        (previous-row nil))
    (dolist (row rows)
      (when (and previous-row (< (nth 1 previous-row) (nth 0 row)))
        (let ((gap-start (nth 1 previous-row))
              (gap-end (nth 0 row)))
          (push (list "GAP"
                      (my/org-clocklog--fmt-hhmm gap-start)
                      (my/org-clocklog--fmt-hhmm gap-end)
                      (my/org-clocklog--fmt-dur (/ (- gap-end gap-start) 60.0)))
                display-rows)))
      (push (list (org-timeviz-dashboard--link-description (nth 3 row))
                  (my/org-clocklog--fmt-hhmm (nth 0 row))
                  (my/org-clocklog--fmt-hhmm (nth 1 row))
                  (my/org-clocklog--fmt-dur (nth 2 row)))
            display-rows)
      (setq previous-row row))
    (setq display-rows (nreverse display-rows))
    (if display-rows
        (org-timeviz-dashboard--render-table
         '("Task" "Start" "End" "Duration")
         display-rows)
      (format "No clocked intervals on %s." date-str))))

(defun org-timeviz-dashboard--rows-minutes (rows)
  "Return total minutes from clocklog ROWS."
  (let ((total 0.0))
    (dolist (row rows total)
      (setq total (+ total (nth 2 row))))))

(defun org-timeviz-dashboard--day-total (rows)
  "Return total logged duration from clocklog ROWS."
  (my/org-clocklog--fmt-dur
   (org-timeviz-dashboard--rows-minutes rows)))

(defun org-timeviz-dashboard--date-plus-days (date-str days)
  "Return DATE-STR plus DAYS as YYYY-MM-DD without DST arithmetic."
  (let* ((parts (mapcar #'string-to-number (split-string date-str "-")))
         (year (nth 0 parts))
         (month (nth 1 parts))
         (day (nth 2 parts))
         (absolute (calendar-absolute-from-gregorian (list month day year)))
         (gregorian (calendar-gregorian-from-absolute (+ absolute days))))
    (format "%04d-%02d-%02d"
            (nth 2 gregorian)
            (nth 0 gregorian)
            (nth 1 gregorian))))

(defun org-timeviz-dashboard--week-total (week-start-str files)
  "Return total logged duration in FILES for the seven days from WEEK-START-STR."
  (let ((total 0.0))
    (dotimes (offset 7)
      (setq total
            (+ total
               (org-timeviz-dashboard--rows-minutes
                (my/org-clocklog-rows
                 (org-timeviz-dashboard--date-plus-days week-start-str offset)
                 files)))))
    (my/org-clocklog--fmt-dur total)))

(defun org-timeviz-dashboard--date-argument-p (value)
  "Return non-nil when command-line argument VALUE is a YYYY-MM-DD date."
  (string-match-p "^[0-9]\\{4\\}-[0-9]\\{2\\}-[0-9]\\{2\\}$" value))

(defun org-timeviz-dashboard-main ()
  "Emit one marked JSON dashboard payload.
The command-line arguments are the report dates followed by the Org files to
scan.  The user's `org-agenda-files' is neither used nor changed."
  (mapc #'org-timeviz-dashboard--require-helper
        '(my/org-clock-suspects
          my/org--collect-ts-pos
          my/org--ts->sec
          my/org-clocklog-rows
          my/org-clocklog--fmt-hhmm
          my/org-clocklog--fmt-dur))
  (let* ((args (remove "--" command-line-args-left))
         (dates (cl-remove-if-not #'org-timeviz-dashboard--date-argument-p args))
         (files (cl-remove-if #'org-timeviz-dashboard--date-argument-p args))
         (day (or (nth 0 dates) (format-time-string "%Y-%m-%d")))
         (day-total-day (or (nth 1 dates) day))
         (week-start (or (nth 2 dates) day))
         (day-rows (my/org-clocklog-rows day files))
         (day-total-rows (my/org-clocklog-rows day-total-day files))
         (intervals (org-timeviz-dashboard--all-intervals files))
         (payload
          `((suspects . ,(org-timeviz-dashboard--suspect-text files intervals))
            (overlaps . ,(org-timeviz-dashboard--overlap-records intervals))
            (chronological . ,(org-timeviz-dashboard--clocklog-text day day-rows))
            (day_total . ,(org-timeviz-dashboard--day-total day-total-rows))
            (week_total . ,(org-timeviz-dashboard--week-total week-start files)))))
    ;; Consumed here, so Emacs does not visit the files again after this script,
    ;; which could prompt if one was saved meanwhile.
    (setq command-line-args-left nil)
    (princ org-timeviz-dashboard--json-prefix)
    (princ (json-encode payload))
    (princ "\n")))

(when noninteractive
  (org-timeviz-dashboard-main))
