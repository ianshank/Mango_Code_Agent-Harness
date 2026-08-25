package governance

import org.junit.platform.launcher.TestExecutionListener
import org.junit.platform.launcher.TestIdentifier
import org.junit.platform.launcher.TestPlan
import java.io.File

/**
 * Records skipped-test evidence. JUnit catches exceptions thrown by a
 * TestExecutionListener, so this listener deliberately does NOT attempt to fail
 * the run. Gradle task verifyNoSkippedTests reads this evidence and fails.
 */
public class ZeroSkipListener : TestExecutionListener {
    private val target: File by lazy { File(System.getProperty("governance.skipEvents", "build/governance/runtime-skips.tsv")) }
    override fun testPlanExecutionStarted(testPlan: TestPlan) { target.parentFile.mkdirs(); target.writeText("") }
    override fun executionSkipped(testIdentifier: TestIdentifier, reason: String) {
        val safeReason = reason.replace('\t', ' ').replace('\n', ' ')
        val safeDisplay = testIdentifier.displayName.replace('\t', ' ').replace('\n', ' ')
        target.appendText("${testIdentifier.uniqueId}\t$safeDisplay\t$safeReason\n")
    }
}
