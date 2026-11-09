;;; Export Org CLOCK records as JSONL (batch) -*- lexical-binding: t; -*-

(require 'cl-lib)
(require 'org)
(require 'json)

(declare-function org-timeviz-clock-read "org_timeviz_clock" (file &optional metadata))

(setq org-use-tag-inheritance t)

;; `org-archive-subtree' records these on the root of each subtree it moves.
;; ARCHIVE_TIME is not among them because archiving to an in-file archive
;; sibling sets it too, and such a subtree keeps its real path and tags.
(defconst org-timeviz--archive-context-properties
  '("ARCHIVE_FILE" "ARCHIVE_OLPATH" "ARCHIVE_CATEGORY" "ARCHIVE_ITAGS")
  "Properties marking the root of a subtree archived by `org-archive-subtree'.")

(defun org-timeviz--archived-root-p ()
  "Return non-nil when the heading at point is the root of an archived subtree."
  (cl-some (lambda (property) (org-entry-get nil property))
           org-timeviz--archive-context-properties))

(defun org-timeviz--outline-path ()
  "Return outline path as a list of headings from top to current.
Within an archived subtree, the original path Org recorded in ARCHIVE_OLPATH
replaces the archive file's own headings above the subtree."
  (save-excursion
    (org-back-to-heading t)
    (let ((parts nil)
          (archived-root nil))
      (while (progn
               (push (org-get-heading t t t t) parts)
               (setq archived-root (org-timeviz--archived-root-p))
               (and (not archived-root) (org-up-heading-safe))))
      (if archived-root
          (append (split-string (or (org-entry-get nil "ARCHIVE_OLPATH") "") "/" t)
                  parts)
        parts))))

(defun org-timeviz--effective-tags ()
  "Return the tags of the heading at point, including archived inherited tags.
Org stores the tags an archived subtree inherited in ARCHIVE_ITAGS, and
`org-archive-subtree-add-inherited-tags' may also copy them onto the heading,
so each tag is returned only once."
  (let ((archived-tags nil))
    (save-excursion
      (while (progn
               (let ((itags (org-entry-get nil "ARCHIVE_ITAGS")))
                 (when itags
                   (setq archived-tags (append archived-tags (split-string itags)))))
               (org-up-heading-safe))))
    ;; Inherited tags first, matching the order of `org-get-tags'.
    (delete-dups (append archived-tags (org-get-tags) nil))))

(defun org-timeviz--category ()
  "Return the category of the heading at point as it was before archiving."
  (or (org-entry-get nil "ARCHIVE_CATEGORY" t)
      (org-get-category)))

(defun org-timeviz--emit-jsonl (obj)
  "Emit OBJ as a single JSON line."
  (princ (json-encode obj))
  (princ "\n"))

(load (expand-file-name "org_timeviz_clock.el"
                             (file-name-directory (or load-file-name buffer-file-name)))
      nil t)

(defun org-timeviz--export-file (file)
  "Export closed CLOCK records from FILE as JSONL to stdout."
  (dolist (clock (car (org-timeviz-clock-read
                      file (lambda ()
                             (list :path (org-timeviz--outline-path)
                                   :tags (org-timeviz--effective-tags)
                                   :category (org-timeviz--category))))))
    ;; Reports have always excluded running clocks.  Dashboard overlaps include
    ;; them, but use the same native extraction.
    (unless (plist-get clock :open)
      (org-timeviz--emit-jsonl
       `((file . ,(expand-file-name file))
         (start . ,(format-time-string "%Y-%m-%dT%H:%M:%S" (plist-get clock :start)))
         (end . ,(format-time-string "%Y-%m-%dT%H:%M:%S" (plist-get clock :end)))
         (outline_path . ,(plist-get clock :path))
         (headline . ,(plist-get clock :heading))
         (tags . ,(plist-get clock :tags))
         (category . ,(plist-get clock :category)))))))

(defun org-timeviz-export-main ()
  "Main entry point for batch export. Reads files from command-line-args-left."
  (dolist (f command-line-args-left)
    (when (and f (file-exists-p f))
      (org-timeviz--export-file f))))

(when noninteractive
  (org-timeviz-export-main))
