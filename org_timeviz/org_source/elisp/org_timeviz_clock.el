;;; org_timeviz_clock.el --- Native clock extraction -*- lexical-binding: t; -*-

(require 'org)
(require 'org-element)
(require 'org-duration)
(require 'org-id)
(require 'cl-lib)

(defun org-timeviz-clock-read (file &optional metadata)
  "Return (CLOCKS ISSUES) from FILE without visiting it or running user hooks.
Each clock is a plist.  METADATA, if non-nil, is called at its heading and
returns additional plist fields.  Org owns timestamp and CLOCK interpretation.
The raw-line scan only finds CLOCK-looking lines omitted by Org's parser;
it deliberately does not attempt to recover timestamps from malformed input."
  (with-temp-buffer
    (insert-file-contents file)
    (let ((org-mode-hook nil)
          (org-inhibit-startup t))
      (org-mode))
    (let ((tree (org-element-parse-buffer))
          (recognized (make-hash-table :test #'eql))
          clocks issues)
      (org-element-map tree 'clock
        (lambda (clock)
          (let* ((pos (org-element-property :begin clock))
                 (line (line-number-at-pos pos))
                 (stamp (org-element-property :value clock))
                 (open (eq (org-element-property :status clock) 'running))
                 (start (org-timestamp-to-time stamp))
                 (end (unless open (org-timestamp-to-time stamp t)))
                 (duration (org-element-property :duration clock)))
            (puthash line t recognized)
            (goto-char pos)
            (let ((raw (buffer-substring-no-properties
                        (line-beginning-position) (line-end-position))))
              (when (org-before-first-heading-p)
                (push (list (file-name-nondirectory file) "(no heading)"
                            "No owning heading" raw (format "Line %d" line)) issues))
              (unless (org-before-first-heading-p)
                (org-back-to-heading t)
                (let ((heading (org-get-heading t t t t)))
                  (push (append
                         (list :start start :end end :open open :position pos
                               :line line :heading heading :id (org-id-get)
                               :file file :timestamp stamp :duration duration)
                         (when metadata (funcall metadata)))
                        clocks)
                  (let ((issue
                         (cond
                          (open "Open clock")
                          ((not (time-less-p start end)) "Non-positive duration")
                          ((and duration
                                (/= (org-duration-to-minutes duration)
                                    (/ (float-time (time-subtract end start)) 60.0)))
                           "Declared-duration mismatch"))))
                    (when issue
                      (push (list (file-name-nondirectory file) heading issue raw
                                  (format "Line %d" line)) issues)))))))))
      (goto-char (point-min))
      (while (re-search-forward "^[ \t]*CLOCK:" nil t)
        (let ((line (line-number-at-pos (match-beginning 0))))
          (unless (gethash line recognized)
            (let ((raw (buffer-substring-no-properties
                        (line-beginning-position) (line-end-position)))
                  (heading (save-excursion
                             (if (org-before-first-heading-p) "(no heading)"
                               (org-back-to-heading t)
                               (org-get-heading t t t t)))))
              (push (list (file-name-nondirectory file) heading "Malformed CLOCK"
                          raw (format "Line %d" line)) issues)))))
      (list (nreverse clocks) (nreverse issues)))))

(defun org-timeviz-clock-identity (timestamp &optional end)
  "Format TIMESTAMP's local components, using its END when requested.
This is the persistent overlap identity; no timezone conversion is involved."
  (let ((suffix (if end "end" "start")))
    (apply #'format "%04d-%02d-%02dT%02d:%02d"
           (mapcar (lambda (part)
                     (org-element-property
                      (intern (concat ":" part "-" suffix)) timestamp))
                   '("year" "month" "day" "hour" "minute")))))

(provide 'org_timeviz_clock)
;;; org_timeviz_clock.el ends here
