import asyncio

from pyground.kernel import KernelClient


def test_worker_namespace_and_interrupts_are_transactional(tmp_path) -> None:
    async def exercise_kernel() -> None:
        kernel = KernelClient(tmp_path / "kernel.py")
        try:
            loaded = await kernel.sync("value = 1")
            assert loaded.state == "ok"
            assert loaded.symbol_count == 1

            editor_loop = asyncio.create_task(
                kernel.sync("value = 2\nwhile True:\n    pass")
            )
            await asyncio.sleep(0.2)
            assert kernel.interrupt() is True
            interrupted = await asyncio.wait_for(editor_loop, 3)
            assert interrupted.interrupted is True

            retained = await kernel.execute("value")
            assert retained.display == "1"

            repl_loop = asyncio.create_task(kernel.execute("while True: pass"))
            await asyncio.sleep(0.2)
            assert kernel.interrupt() is True
            interrupted = await asyncio.wait_for(repl_loop, 3)
            assert interrupted.interrupted is True

            usable = await kernel.execute("value + 1")
            assert usable.display == "2"
        finally:
            kernel.close()

    asyncio.run(exercise_kernel())
