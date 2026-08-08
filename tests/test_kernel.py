import asyncio

from scrappad.kernel import KernelClient


def discard_output(_: str) -> None:
    pass


def test_worker_namespace_and_interrupts_are_transactional(tmp_path) -> None:
    async def exercise_kernel() -> None:
        kernel = KernelClient(tmp_path / "kernel.py")
        try:
            loaded = await kernel.sync("value = 1", on_output=discard_output)
            assert loaded.state == "ok"
            assert loaded.symbol_count == 1

            editor_output: list[str] = []
            editor_loop = asyncio.create_task(
                kernel.sync(
                    "value = 2\nwhile True:\n    print('editor')",
                    on_output=editor_output.append,
                )
            )
            for _ in range(100):
                if editor_output:
                    break
                await asyncio.sleep(0.01)
            assert "editor\n" in "".join(editor_output)
            assert kernel.interrupt() is True
            interrupted = await asyncio.wait_for(editor_loop, 3)
            assert interrupted.interrupted is True
            assert "<output truncated>" not in "".join(editor_output)

            retained = await kernel.execute("value", on_output=discard_output)
            assert retained.display == "1"

            repl_loop = asyncio.create_task(
                kernel.execute("while True: pass", on_output=discard_output)
            )
            await asyncio.sleep(0.2)
            assert kernel.interrupt() is True
            interrupted = await asyncio.wait_for(repl_loop, 3)
            assert interrupted.interrupted is True

            usable = await kernel.execute("value + 1", on_output=discard_output)
            assert usable.display == "2"

            printed_output: list[str] = []
            await kernel.execute("print('hello')", on_output=printed_output.append)
            assert "".join(printed_output) == "hello\n"

            output_chunks: list[str] = []
            printing_loop = asyncio.create_task(
                kernel.execute(
                    "while True: print('hi')",
                    on_output=output_chunks.append,
                )
            )
            for _ in range(100):
                if output_chunks:
                    break
                await asyncio.sleep(0.01)
            assert "hi\n" in "".join(output_chunks)
            assert kernel.interrupt() is True
            interrupted = await asyncio.wait_for(printing_loop, 3)
            assert interrupted.interrupted is True
            assert interrupted.error == "KeyboardInterrupt"
            assert "<output truncated>" not in "".join(output_chunks)
        finally:
            kernel.close()

    asyncio.run(exercise_kernel())
