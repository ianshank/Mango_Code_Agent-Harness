import org.gradle.api.artifacts.dsl.LockMode
import org.gradle.api.tasks.testing.Test
import org.gradle.api.GradleException
import org.gradle.testing.jacoco.tasks.JacocoCoverageVerification
import org.gradle.testing.jacoco.tasks.JacocoReport
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("jvm") version "2.2.20"
    jacoco
    id("com.diffplug.spotless") version "7.2.1"
    id("io.gitlab.arturbosch.detekt") version "1.23.8"
    id("com.autonomousapps.dependency-analysis") version "2.19.0"
}

repositories { mavenCentral() }

dependencyLocking {
    lockAllConfigurations()
    lockMode.set(LockMode.STRICT)
}

dependencies {
    testImplementation(kotlin("test"))
    testImplementation("org.junit.jupiter:junit-jupiter:5.14.0")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher:1.14.0")
}

kotlin {
    explicitApi()
    compilerOptions { jvmTarget.set(JvmTarget.JVM_21); allWarningsAsErrors.set(true) }
}

tasks.withType<Test>().configureEach {
    useJUnitPlatform()
    systemProperty("governance.skipEvents", layout.buildDirectory.file("governance/runtime-skips.tsv").get().asFile.absolutePath)
}

val verifyNoSkippedTests by tasks.registering {
    group = "verification"
    dependsOn(tasks.test)
    doLast {
        exec { commandLine("python3", "scripts/verify_zero_skips.py", "--junit-events", "build/governance/runtime-skips.tsv") }
    }
}

tasks.named("check") { dependsOn(verifyNoSkippedTests) }

jacoco { toolVersion = "0.8.13" }
tasks.named<JacocoReport>("jacocoTestReport") { dependsOn(tasks.test); reports { xml.required.set(true); html.required.set(true) } }
tasks.named<JacocoCoverageVerification>("jacocoTestCoverageVerification") {
    dependsOn(tasks.test)
    violationRules {
        rule { limit { counter = "LINE"; minimum = "0.90".toBigDecimal() }; limit { counter = "BRANCH"; minimum = "0.80".toBigDecimal() } }
        rule { element = "CLASS"; limit { counter = "LINE"; minimum = "0.90".toBigDecimal() }; limit { counter = "BRANCH"; minimum = "0.80".toBigDecimal() } }
    }
}

tasks.register("typesCheck") { dependsOn("compileKotlin", "compileTestKotlin") }
