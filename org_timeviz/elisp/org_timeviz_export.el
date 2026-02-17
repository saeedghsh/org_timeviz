;;; Export Org CLOCK records as JSONL (batch) -*- lexical-binding: t; -*-

(require 'org)
(require 'json)

(setq org-use-tag-inheritance t)

(defun org-timeviz--ts-to-time (ts)
  "Convert Org timestamp string TS to Emacs time."
  (let* ((p (org-parse-time-string ts))
         (sec (or (nth 0 p) 0))
         (min (or (nth 1 p) 0))
         (hour (or (nth 2 p) 0))
         (day (or (nth 3 p) 1))
         (mon (or (nth 4 p) 1))
         (year (or (nth 5 p) 1970)))
    (encode-time sec min hour day mon year)))

(defun org-timeviz--ts-to-iso (ts)
  "Convert Org timestamp string TS to ISO-8601 (local time)."
  (format-time-string "%Y-%m-%dT%H:%M:%S" (org-timeviz--ts-to-time ts)))

(defun org-timeviz--extract-clock (s)
  "Extract (START END) timestamp strings from CLOCK line S, or nil."
  (when (string-match "CLOCK:[[:space:]]*\\[\\([^]]+\\)\\][[:space:]]*--[[:space:]]*\\[\\([^]]+\\)\\]" s)
    (list (match-string 1 s) (match-string 2 s))))

(defun org-timeviz--outline-path ()
  "Return outline path as a list of headings from top to current."
  (save-excursion
    (org-back-to-heading t)
    (let ((parts (list (org-get-heading t t t t))))
      (while (org-up-heading-safe)
        (push (org-get-heading t t t t) parts))
      parts)))

(defun org-timeviz--emit-jsonl (obj)
  "Emit OBJ as a single JSON line."
  (princ (json-encode obj))
  (princ "\n"))

(defun org-timeviz--export-file (file)
  "Export all CLOCK records from FILE as JSONL to stdout."
  (with-temp-buffer
    (insert-file-contents file)
    (org-mode)
    (goto-char (point-min))
    (while (re-search-forward "^[[:space:]]*CLOCK:" nil t)
      (let* ((line (buffer-substring-no-properties (line-beginning-position) (line-end-position)))
             (pair (org-timeviz--extract-clock line)))
        (when pair
          (let ((start-ts (nth 0 pair))
                (end-ts (nth 1 pair)))
            (save-excursion
              (condition-case nil
                  (progn
                    (org-back-to-heading t)
                    (let* ((path (org-timeviz--outline-path))
                           (headline (car (last path)))
                           (tags (org-get-tags))
                           (category (org-get-category)))
                      (org-timeviz--emit-jsonl
                       `((file . ,(expand-file-name file))
                         (start . ,(org-timeviz--ts-to-iso start-ts))
                         (end . ,(org-timeviz--ts-to-iso end-ts))
                         (outline_path . ,path)
                         (headline . ,headline)
                         (tags . ,tags)
                         (category . ,category)))))
                (error nil)))))))))

(defun org-timeviz-export-main ()
  "Main entry point for batch export.
Reads files from command-line-args-left and prints JSONL."
  (dolist (f command-line-args-left)
    (when (and f (file-exists-p f))
      (org-timeviz--export-file f))))

(when noninteractive
  (org-timeviz-export-main))
