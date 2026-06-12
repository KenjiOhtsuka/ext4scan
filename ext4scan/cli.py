import argparse
from .journal_reader import JournalReader
from .jbd2_parser import JBD2Parser
from .timeline import Timeline

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("device")
    parser.add_argument("--output", default="timeline.json")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    # print(args.device)
    reader = JournalReader(args.device, debug=args.debug)
    if not reader.journal_blocks:
        print("No internal ext4 journal found. Timeline will be empty.")
        # timeline.json を空で作るならここで return してもよい
        Timeline().save(args.output)
        return

    parser = JBD2Parser()
    timeline = Timeline()

    for block in reader.read_journal_blocks():
        event = parser.parse_block(block)
        if event:
            timeline.add(event)
    print(timeline)
    timeline.save(args.output)

if __name__ == "__main__":
    main()
