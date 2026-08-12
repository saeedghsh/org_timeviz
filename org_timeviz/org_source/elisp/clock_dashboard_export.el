;;; Render live clock dashboard text as JSON (batch) -*- lexical-binding: t; -*-

(require 'calendar)
(require 'cl-lib)
(require 'json)
(require 'org)

;; The user's init-org.el resolves dangling clocks whenever an Org buffer opens.
;; Dashboard reads must never mutate source Org files.
(when (boundp 'my/org-auto-resolve-dangling-clocks)
  (setq my/org-auto-resolve-dangling-clocks nil))

(defconst org-timeviz-dashboard--json-prefix "ORG_TIMEVIZ_CLOCK_DASHBOARD_JSON:")

(defun org-timeviz-dashboard--require-helper (symbol)
  "Fail clearly when the user's init file does not define SYMBOL."
  (unless (fboundp symbol)
    (error "Clock dashboard requires %S in the configured Emacs init file" symbol)))

(defun org-timeviz-dashboard--link-description (value)
  "Return the visible description from Org link VALUE, when present."
  (if (and (stringp value)
           (string-match "\\[\\[[^]]+\\]\\[\\([^]]+\\)\\]\\]" value))
      (match-string 1 value)
    (format "%s" value)))

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

(defun org-timeviz-dashboard--suspect-text ()
  "Render clock-line issues and overlapping intervals across agenda files."
  (let* ((raw-issues (my/org-clock-suspects (org-agenda-files)))
         (issue-rows
          (mapcar
           (lambda (row)
             (list (nth 0 row)
                   (org-timeviz-dashboard--link-description (nth 1 row))
                   (nth 2 row)
                   (nth 3 row)
                   (nth 4 row)))
           raw-issues))
         (overlap-rows (org-timeviz-dashboard--overlap-rows))
         (sections '()))
    (when issue-rows
      (push
       (concat
        "Clock-line issues:\n"
        (org-timeviz-dashboard--render-table
         '("File" "Heading" "Issue" "Clock line" "Details")
         issue-rows))
       sections))
    (when overlap-rows
      (push
       (concat
        "Overlapping clocks:\n"
        (org-timeviz-dashboard--render-table
         '("Task A" "Interval A" "Task B" "Interval B")
         overlap-rows))
       sections))
    (if sections
        (mapconcat #'identity (nreverse sections) "\n\n")
      "All CLOCK lines look standard; no overlapping intervals found.")))

(defun org-timeviz-dashboard--all-intervals ()
  "Collect closed and open clock intervals from all agenda files."
  (let ((rows '())
        (now (float-time (current-time))))
    (dolist (file (org-agenda-files))
      (with-current-buffer (find-file-noselect file)
        (save-excursion
          (goto-char (point-min))
          (while (re-search-forward "^ *CLOCK: *\\(.*\\)$" nil t)
            (let* ((payload (match-string 1))
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
                                   open)
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

(defun org-timeviz-dashboard--overlap-rows ()
  "Return readable rows for every pair of overlapping clock intervals."
  (let ((active '())
        (overlaps '()))
    (dolist (row (org-timeviz-dashboard--all-intervals))
      (setq active
            (cl-remove-if
             (lambda (other) (<= (nth 1 other) (nth 0 row)))
             active))
      (dolist (other active)
        (push
         (list (org-timeviz-dashboard--task-label other)
               (org-timeviz-dashboard--interval-label other)
               (org-timeviz-dashboard--task-label row)
               (org-timeviz-dashboard--interval-label row))
         overlaps))
      (push row active))
    (nreverse overlaps)))

(defun org-timeviz-dashboard--clocklog-text (date-str rows)
  "Render chronological clock ROWS for DATE-STR."
  (let* ((display-rows
          (mapcar
           (lambda (row)
             (list (org-timeviz-dashboard--link-description (nth 3 row))
                   (my/org-clocklog--fmt-hhmm (nth 0 row))
                   (my/org-clocklog--fmt-hhmm (nth 1 row))
                   (my/org-clocklog--fmt-dur (nth 2 row))))
           rows)))
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

(defun org-timeviz-dashboard--week-total (week-start-str)
  "Return total logged duration for the seven days from WEEK-START-STR."
  (let ((total 0.0))
    (dotimes (offset 7)
      (setq total
            (+ total
               (org-timeviz-dashboard--rows-minutes
                (my/org-clocklog-rows
                 (org-timeviz-dashboard--date-plus-days week-start-str offset)
                 (org-agenda-files))))))
    (my/org-clocklog--fmt-dur total)))

(defun org-timeviz-dashboard-main ()
  "Emit one marked JSON dashboard payload using command-line date arguments."
  (mapc #'org-timeviz-dashboard--require-helper
        '(my/org-clock-suspects
          my/org--collect-ts-pos
          my/org--ts->sec
          my/org-clocklog-rows
          my/org-clocklog--fmt-hhmm
          my/org-clocklog--fmt-dur))
  (let* ((args (cl-remove-if-not
                (lambda (value)
                  (and (stringp value)
                       (string-match-p "^[0-9]\\{4\\}-[0-9]\\{2\\}-[0-9]\\{2\\}$" value)))
                command-line-args-left))
         (day (or (nth 0 args) (format-time-string "%Y-%m-%d")))
         (day-total-day (or (nth 1 args) day))
         (week-start (or (nth 2 args) day))
         (day-rows (my/org-clocklog-rows day (org-agenda-files)))
         (day-total-rows (my/org-clocklog-rows day-total-day (org-agenda-files)))
         (payload
          `((suspects . ,(org-timeviz-dashboard--suspect-text))
            (chronological . ,(org-timeviz-dashboard--clocklog-text day day-rows))
            (day_total . ,(org-timeviz-dashboard--day-total day-total-rows))
            (week_total . ,(org-timeviz-dashboard--week-total week-start)))))
    (princ org-timeviz-dashboard--json-prefix)
    (princ (json-encode payload))
    (princ "\n")))

(when noninteractive
  (org-timeviz-dashboard-main))
