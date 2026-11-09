;;; agenda_export.el --- Evaluate trusted agenda configuration -*- lexical-binding: t; -*-

(require 'org)
(require 'json)

(defun org-timeviz-agenda-main ()
  "Load one explicitly configured, trusted Lisp file and emit effective values.
This is evaluation, not a sandbox.  Run separately from Org file readers so
configuration hooks and file-local code never run while reading source files."
  (let* ((args (remove "--" command-line-args-left))
         (file (car args))
         (variable (intern (cadr args)))
         (enable-local-variables nil)
         (enable-local-eval nil)
         (org-agenda-files nil))
    (setq command-line-args-left nil)
    (load (expand-file-name file) nil t t)
    (let* ((org-agenda-files (and (boundp variable) (symbol-value variable)))
           (files (org-agenda-files t))
           (keywords (with-temp-buffer
                       (let ((org-mode-hook nil) (org-inhibit-startup t))
                         (org-mode))
                       org-todo-keywords-1)))
      (princ "ORG_TIMEVIZ_AGENDA_JSON:")
      (princ (json-encode `((files . ,(vconcat files))
                            (todo_keywords . ,(vconcat keywords)))))
      (princ "\n"))))

(when noninteractive
  (org-timeviz-agenda-main))
;;; agenda_export.el ends here
