"""Classes for storing and processing test results."""

from __future__ import absolute_import, print_function

import datetime
import json

from lib.util import (
    display,
    EnvironmentConfig,
)


class TestConfig(EnvironmentConfig):
    """Configuration common to all test commands."""
    def __init__(self, args, command):
        """
        :type args: any
        :type command: str
        """
        super(TestConfig, self).__init__(args, command)

        self.coverage = args.coverage  # type: bool
        self.include = args.include  # type: list [str]
        self.exclude = args.exclude  # type: list [str]
        self.require = args.require  # type: list [str]

        self.changed = args.changed  # type: bool
        self.tracked = args.tracked  # type: bool
        self.untracked = args.untracked  # type: bool
        self.committed = args.committed  # type: bool
        self.staged = args.staged  # type: bool
        self.unstaged = args.unstaged  # type: bool
        self.changed_from = args.changed_from  # type: str
        self.changed_path = args.changed_path  # type: list [str]

        self.lint = args.lint if 'lint' in args else False  # type: bool
        self.junit = args.junit if 'junit' in args else False  # type: bool


class TestResult(object):
    """Base class for test results."""
    def __init__(self, command, test, python_version=None):
        """
        :type command: str
        :type test: str
        :type python_version: str
        """
        self.command = command
        self.test = test
        self.python_version = python_version
        self.name = self.test or self.command

        if self.python_version:
            self.name += '-python-%s' % self.python_version

        try:
            import junit_xml
        except ImportError:
            junit_xml = None

        self.junit = junit_xml

    def write(self, args):
        """
        :type args: TestConfig
        """
        self.write_console()
        self.write_bot(args)

        if args.lint:
            self.write_lint()

        if args.junit:
            if self.junit:
                self.write_junit(args)
            else:
                display.warning('Skipping junit xml output because the `junit-xml` python package was not found.', unique=True)

    def write_console(self):
        """Write results to console."""
        pass

    def write_lint(self):
        """Write lint results to stdout."""
        pass

    def write_bot(self, args):
        """
        :type args: TestConfig
        """
        pass

    def write_junit(self, args):
        """
        :type args: TestConfig
        """
        pass

    def create_path(self, directory, extension):
        """
        :type directory: str
        :type extension: str
        :rtype: str
        """
        path = 'test/results/%s/ansible-test-%s' % (directory, self.command)

        if self.test:
            path += '-%s' % self.test

        if self.python_version:
            path += '-python-%s' % self.python_version

        path += extension

        return path

    def save_junit(self, args, test_case, properties=None):
        """
        :type args: TestConfig
        :type test_case: junit_xml.TestCase
        :type properties: dict[str, str] | None
        :rtype: str | None
        """
        path = self.create_path('junit', '.xml')

        test_suites = [
            self.junit.TestSuite(
                name='ansible-test',
                test_cases=[test_case],
                timestamp=datetime.datetime.utcnow().replace(microsecond=0).isoformat(),
                properties=properties,
            ),
        ]

        report = self.junit.TestSuite.to_xml_string(test_suites=test_suites, prettyprint=True, encoding='utf-8')

        if args.explain:
            return

        with open(path, 'wb') as xml:
            xml.write(report.encode('utf-8', 'strict'))


class TestSuccess(TestResult):
    """Test success."""
    def __init__(self, command, test, python_version=None):
        """
        :type command: str
        :type test: str
        :type python_version: str
        """
        super(TestSuccess, self).__init__(command, test, python_version)

    def write_junit(self, args):
        """
        :type args: TestConfig
        """
        test_case = self.junit.TestCase(classname=self.command, name=self.name)

        self.save_junit(args, test_case)


class TestSkipped(TestResult):
    """Test skipped."""
    def __init__(self, command, test, python_version=None):
        """
        :type command: str
        :type test: str
        :type python_version: str
        """
        super(TestSkipped, self).__init__(command, test, python_version)

    def write_console(self):
        """Write results to console."""
        display.info('No tests applicable.', verbosity=1)

    def write_junit(self, args):
        """
        :type args: TestConfig
        """
        test_case = self.junit.TestCase(classname=self.command, name=self.name)
        test_case.add_skipped_info('No tests applicable.')

        self.save_junit(args, test_case)


class TestFailure(TestResult):
    """Test failure."""
    def __init__(self, command, test, python_version=None, messages=None, summary=None):
        """
        :type command: str
        :type test: str
        :type python_version: str
        :type messages: list[TestMessage]
        :type summary: str
        """
        super(TestFailure, self).__init__(command, test, python_version)

        self.messages = messages
        self.summary = summary

    def write_console(self):
        """Write results to console."""
        if self.summary:
            display.error(self.summary)
        else:
            if self.python_version:
                specifier = ' on python %s' % self.python_version
            else:
                specifier = ''

            display.error('Found %d %s issue(s)%s which need to be resolved:' % (len(self.messages), self.test or self.command, specifier))

            for message in self.messages:
                display.error(message)

    def write_lint(self):
        """Write lint results to stdout."""
        if self.summary:
            command = self.format_command()
            message = 'The test `%s` failed. See stderr output for details.' % command
            path = 'test/runner/ansible-test'
            message = TestMessage(message, path)
            print(message)
        else:
            for message in self.messages:
                print(message)

    def write_junit(self, args):
        """
        :type args: TestConfig
        """
        title = self.format_title()
        output = self.format_block()

        test_case = self.junit.TestCase(classname=self.command, name=self.name)

        # Include a leading newline to improve readability on Shippable "Tests" tab.
        # Without this, the first line becomes indented.
        test_case.add_failure_info(message=title, output='\n%s' % output)

        self.save_junit(args, test_case)

    def write_bot(self, args):
        """
        :type args: TestConfig
        """
        message = self.format_title()
        output = self.format_block()

        bot_data = dict(
            results=[
                dict(
                    message=message,
                    output=output,
                ),
            ],
        )

        path = self.create_path('bot', '.json')

        if args.explain:
            return

        with open(path, 'wb') as bot_fd:
            json.dump(bot_data, bot_fd, indent=4, sort_keys=True)
            bot_fd.write('\n')

    def format_command(self):
        """
        :rtype: str
        """
        command = 'ansible-test %s' % self.command

        if self.test:
            command += ' --test %s' % self.test

        if self.python_version:
            command += ' --python %s' % self.python_version

        return command

    def format_title(self):
        """
        :rtype: str
        """
        command = self.format_command()

        if self.summary:
            reason = 'error'
        else:
            reason = 'error' if len(self.messages) == 1 else 'errors'

        title = 'The test `%s` failed with the following %s:' % (command, reason)

        return title

    def format_block(self):
        """
        :rtype: str
        """
        if self.summary:
            block = self.summary
        else:
            block = '\n'.join(str(m) for m in self.messages)

        message = block.strip()

        # Hack to remove ANSI color reset code from SubprocessError messages.
        message = message.replace(display.clear, '')

        return message


class TestMessage(object):
    """Single test message for one file."""
    def __init__(self, message, path, line=0, column=0, level='error', code=None):
        """
        :type message: str
        :type path: str
        :type line: int
        :type column: int
        :type level: str
        :type code: str | None
        """
        self.path = path
        self.line = line
        self.column = column
        self.level = level
        self.code = code
        self.message = message

    def __str__(self):
        if self.code:
            msg = '%s %s' % (self.code, self.message)
        else:
            msg = self.message

        return '%s:%s:%s: %s' % (self.path, self.line, self.column, msg)
