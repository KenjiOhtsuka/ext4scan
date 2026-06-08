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
    reader = JournalReader(args.device)
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
