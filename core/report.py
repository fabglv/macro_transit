"""Console reporting: section headers, table previews, and a copy of everything in a log file."""
import os
import sys


def section(title):
    """A visible break in the log between the steps of a run."""
    print(f"\n{'=' * 96}\n{title}\n{'=' * 96}")


def preview(frame, title, rows=5, columns=None, width=26):
    """First rows of a table, so the data can be read rather than only summarised.

    Drops the geometry column, which prints as an unreadable coordinate dump.
    """
    view = frame.drop(columns="geometry", errors="ignore")
    if columns:
        view = view[columns]
    print(f"\n{title} - first {rows} of {len(frame):,} rows:")
    print(view.head(rows).to_string(index=False, max_colwidth=width))


class Tee:
    """Write what is printed both to the console and to a log file."""

    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.file = open(path, "w", encoding="utf-8")
        self.console = sys.stdout

    def write(self, text):
        self.console.write(text)
        self.file.write(text)

    def flush(self):
        self.console.flush()
        self.file.flush()

    def close(self):
        self.file.close()
