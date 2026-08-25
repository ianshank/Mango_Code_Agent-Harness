package governance

import kotlin.test.Test
import kotlin.test.assertTrue
import java.io.File

public class GovernanceMetaTest {
    @Test public fun `requirement anchors are present`() { assertTrue(PolicyAnchor.requirementIds.containsAll(listOf("C-GOV-1", "R-GOV-2"))) }
    @Test public fun `C-GOV-1 CI uses named targets`() {
        val ci = File(".github/workflows/ci.yml").readText()
        listOf("cov","lint","types","secrets","specs","audit","remotes","projections","traceability","governance").forEach { assertTrue(ci.contains("make $it")) }
    }
    @Test public fun `R-GOV-2 pre-push delegates to shared normalizer`() {
        assertTrue(File("scripts/pre_push_scan.sh").readText().contains("scripts/remotes.py"))
    }
}
