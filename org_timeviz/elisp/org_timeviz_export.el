;;; Export Org CLOCK records as JSONL (batch) -*- lexical-binding: t; -*-

(require 'org)
(require 'json)

(setq org-use-tag-inheritance t)

(setq org-use-tag-inheritance t)

(defun org-timeviz--maybe-configure-todo-keywords ()
  "Configure org-todo-keywords from env or init file (robust, no regex)."
  (let ((override (getenv "ORG_TIMEVIZ_TODO_KEYWORDS"))
        (initfile (getenv "ORG_TIMEVIZ_EMACS_INIT")))
    (cond
     ((and override (> (length override) 0))
      (org-timeviz--set-todo-keywords-from-json override))

     ((and initfile (> (length initfile) 0) (file-exists-p initfile))
      (let ((kws (org-timeviz--extract-todo-keywords-from-init initfile)))
        (when (and (listp kws) kws)
          (setq org-todo-keywords (list (cons 'sequence kws)))
          (org-set-regexps-and-options))))

     (t nil))))

(defun org-timeviz--set-todo-keywords-from-json (s)
  "Set org-todo-keywords from JSON list S."
  (let* ((json-array-type 'list)
         (json-object-type 'alist)
         (kws (json-read-from-string s)))
    (when (and (listp kws) kws)
      (setq org-todo-keywords (list (cons 'sequence kws)))
      (org-set-regexps-and-options))))

(defun org-timeviz--extract-todo-keywords-from-init (file)
  "Extract TODO keywords from (setq org-todo-keywords ...) forms in FILE.
Comments are ignored because we read Lisp forms, not text."
  (let ((found nil))
    (with-temp-buffer
      (insert-file-contents file)
      (goto-char (point-min))
      (condition-case nil
          (while t
            (let ((form (read (current-buffer))))
              (when (and (listp form)
                         (eq (car form) 'setq))
                (let ((kws (org-timeviz--extract-todo-keywords-from-setq form)))
                  (when kws
                    (setq found kws))))))
        (end-of-file nil)))
    found))

(defun org-timeviz--extract-todo-keywords-from-setq (form)
  "If FORM is (setq ... org-todo-keywords VALUE ...), return keyword list or nil."
  (let ((xs (cdr form))
        (result nil))
    (while (and xs (cdr xs))
      (let ((var (car xs))
            (val (cadr xs)))
        (when (eq var 'org-todo-keywords)
          (setq result (org-timeviz--extract-todo-keywords-from-value val))))
      (setq xs (cddr xs)))
    result))

(defun org-timeviz--extract-todo-keywords-from-value (val)
  "Extract strings from org-todo-keywords VAL."
  (let* ((unquoted (org-timeviz--unquote val))
         (strings (org-timeviz--collect-strings unquoted))
         (out nil))
    (dolist (s strings)
      (when (and (stringp s)
                 (> (length s) 0)
                 (not (string= s "|")))
        (setq out (append out (list s)))))
    out))

(defun org-timeviz--unquote (x)
  "If X is (quote ...), return ...; otherwise return X."
  (if (and (listp x) (eq (car x) 'quote) (cdr x))
      (cadr x)
    x))

(defun org-timeviz--collect-strings (x)
  "Collect all string atoms recursively from X."
  (cond
   ((stringp x) (list x))
   ((consp x) (append (org-timeviz--collect-strings (car x))
                      (org-timeviz--collect-strings (cdr x))))
   (t nil)))

(org-timeviz--maybe-configure-todo-keywords)

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
  "Main entry point for batch export. Reads files from command-line-args-left."
  (dolist (f command-line-args-left)
    (when (and f (file-exists-p f))
      (org-timeviz--export-file f))))

(when noninteractive
  (org-timeviz-export-main))
